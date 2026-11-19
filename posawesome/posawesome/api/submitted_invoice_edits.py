import copy
import json
import uuid

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime

from posawesome.posawesome.api.idempotency import (
    doctype_supports_client_request_id,
    find_invoice_by_client_request_id,
    set_invoice_client_request_id,
)
from posawesome.posawesome.api.invoice_processing.creation import (
    _reapply_incoming_payment_amounts,
    _submit_invoice_once,
    trusted_invoice_shift_reassignment,
)
from posawesome.posawesome.api.utils import assert_pos_profile_write_allowed


SUPPORTED_INVOICE_DOCTYPES = {"Sales Invoice", "POS Invoice"}
DEFAULT_EDIT_WINDOW_HOURS = 24
TOP_LEVEL_EDITABLE_FIELDS = (
    "customer",
    "discount_amount",
    "additional_discount_percentage",
    "apply_discount_on",
    "due_date",
)
CUSTOMER_DEPENDENT_FIELDS = (
    "customer_name",
    "title",
    "debit_to",
    "party_account_currency",
    "customer_group",
    "territory",
    "tax_id",
    "tax_category",
    "customer_address",
    "address_display",
    "contact_person",
    "contact_display",
    "contact_mobile",
    "contact_email",
    "shipping_address_name",
    "shipping_address",
    "dispatch_address_name",
    "dispatch_address",
    "language",
    "loyalty_program",
    "loyalty_points",
    "loyalty_amount",
    "redeem_loyalty_points",
)
CHILD_ID_FIELDS = {
    "name",
    "parent",
    "parentfield",
    "parenttype",
    "creation",
    "owner",
    "modified",
    "modified_by",
    "docstatus",
    "_liked_by",
    "__last_sync_on",
}
ITEM_EDITABLE_FIELDS = {
    "item_code",
    "item_name",
    "description",
    "qty",
    "uom",
    "stock_uom",
    "conversion_factor",
    "warehouse",
    "rate",
    "price_list_rate",
    "discount_percentage",
    "discount_amount",
    "is_free_item",
    "batch_no",
    "serial_no",
    "income_account",
    "expense_account",
    "cost_center",
}
PAYMENT_EDITABLE_FIELDS = {
    "mode_of_payment",
    "amount",
    "base_amount",
    "account",
    "type",
    "default",
    "currency",
    "conversion_rate",
}


def _loads(value, default=None):
    if default is None:
        default = {}
    if value is None:
        return copy.deepcopy(default)
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return copy.deepcopy(default)


def _normalize_doctype(doctype):
    doctype = doctype or "Sales Invoice"
    if doctype not in SUPPORTED_INVOICE_DOCTYPES:
        frappe.throw(_("Submitted invoice editing supports Sales Invoice and POS Invoice only."))
    return doctype


def _has_column(doctype, fieldname):
    try:
        return bool(frappe.db.has_column(doctype, fieldname))
    except Exception:
        return False


def _meta_has_field(doctype, fieldname):
    try:
        return bool(frappe.get_meta(doctype).has_field(fieldname))
    except Exception:
        return False


def _get_profile_setting(pos_profile, fieldname, default=None):
    if not pos_profile:
        return default
    if not _meta_has_field("POS Profile", fieldname):
        return default
    value = frappe.db.get_value("POS Profile", pos_profile, fieldname)
    return default if value is None else value


def _get_edit_window_hours(pos_profile):
    raw_value = _get_profile_setting(
        pos_profile,
        "posa_submitted_invoice_edit_window_hours",
        DEFAULT_EDIT_WINDOW_HOURS,
    )
    try:
        hours = flt(raw_value)
    except Exception:
        hours = DEFAULT_EDIT_WINDOW_HOURS
    return hours if hours > 0 else DEFAULT_EDIT_WINDOW_HOURS


def _edit_window_configured():
    return _meta_has_field("POS Profile", "posa_submitted_invoice_edit_window_hours")


def _feature_enabled(pos_profile):
    return cint(_get_profile_setting(pos_profile, "posa_allow_submitted_invoice_edit", 1)) == 1


def _get_active_children(doctype, invoice_name):
    return frappe.get_all(
        doctype,
        filters={"amended_from": invoice_name, "docstatus": ["!=", 2]},
        fields=["name"],
        limit_page_length=1,
    )


def _get_root_invoice_info(doctype, doc):
    current_name = doc.name
    current = {
        "name": doc.name,
        "creation": doc.get("creation"),
        "amended_from": doc.get("amended_from"),
    }
    seen = set()
    amendment_count = 0
    while current.get("amended_from") and current["amended_from"] not in seen:
        seen.add(current_name)
        current_name = current["amended_from"]
        parent = frappe.db.get_value(
            doctype,
            current_name,
            ["name", "creation", "amended_from"],
            as_dict=True,
        )
        if not parent:
            break
        current = parent
        amendment_count += 1
    return {
        "original_invoice": current.get("name") or doc.name,
        "original_creation": current.get("creation") or doc.get("creation"),
        "amendment_count": amendment_count,
    }


def _hours_since(value):
    if not value:
        return 0
    return (now_datetime() - get_datetime(value)).total_seconds() / 3600


def _is_closed_invoice(doc):
    if _has_column(doc.doctype, "pos_closing_entry") and doc.get("pos_closing_entry"):
        return True
    if doc.doctype == "POS Invoice" and doc.get("consolidated_invoice"):
        return True
    if frappe.db.exists(
        "Sales Invoice Reference",
        {
            "parenttype": "POS Closing Shift",
            "parentfield": "pos_transactions",
            "docstatus": 1,
            "sales_invoice" if doc.doctype == "Sales Invoice" else "pos_invoice": doc.name,
        },
    ):
        return True
    return False


def _get_profile_edit_settings(profile_names):
    """Load edit settings once per profile for invoice-list metadata."""

    profile_names = list(dict.fromkeys(name for name in profile_names if name))
    if not profile_names:
        return {}

    fields = ["name"]
    for fieldname in (
        "posa_allow_submitted_invoice_edit",
        "posa_submitted_invoice_edit_window_hours",
    ):
        if _meta_has_field("POS Profile", fieldname):
            fields.append(fieldname)

    rows = frappe.get_all(
        "POS Profile",
        filters={"name": ["in", profile_names]},
        fields=fields,
        limit_page_length=0,
    )
    settings = {
        name: {
            "feature_enabled": True,
            "edit_window_hours": DEFAULT_EDIT_WINDOW_HOURS,
        }
        for name in profile_names
    }
    for row in rows or []:
        enabled = row.get("posa_allow_submitted_invoice_edit")
        raw_hours = row.get("posa_submitted_invoice_edit_window_hours")
        try:
            hours = flt(raw_hours) if raw_hours is not None else DEFAULT_EDIT_WINDOW_HOURS
        except Exception:
            hours = DEFAULT_EDIT_WINDOW_HOURS
        settings[row.get("name")] = {
            "feature_enabled": cint(enabled if enabled is not None else 1) == 1,
            "edit_window_hours": hours if hours > 0 else DEFAULT_EDIT_WINDOW_HOURS,
        }
    return settings


def _get_root_invoice_info_map(doctype, rows):
    """Resolve amendment roots in a bounded number of batched hierarchy queries."""

    invoice_nodes = {
        row.get("name"): {
            "name": row.get("name"),
            "creation": row.get("creation"),
            "amended_from": row.get("amended_from"),
        }
        for row in rows or []
        if row.get("name")
    }
    pending = {
        node.get("amended_from")
        for node in invoice_nodes.values()
        if node.get("amended_from") and node.get("amended_from") not in invoice_nodes
    }
    while pending:
        parents = frappe.get_all(
            doctype,
            filters={"name": ["in", list(pending)]},
            fields=["name", "creation", "amended_from"],
            limit_page_length=0,
        )
        found = set()
        next_pending = set()
        for parent in parents or []:
            parent_name = parent.get("name")
            if not parent_name:
                continue
            found.add(parent_name)
            invoice_nodes[parent_name] = parent
            ancestor = parent.get("amended_from")
            if ancestor and ancestor not in invoice_nodes:
                next_pending.add(ancestor)
        # A missing ancestor previously ended the per-row traversal as well.
        if not found:
            break
        pending = next_pending

    root_info = {}
    for row in rows or []:
        current = row
        seen = set()
        amendment_count = 0
        while current.get("amended_from") and current.get("amended_from") not in seen:
            seen.add(current.get("name"))
            parent = invoice_nodes.get(current.get("amended_from"))
            if not parent:
                break
            current = parent
            amendment_count += 1
        root_info[row.get("name")] = {
            "original_invoice": current.get("name") or row.get("name"),
            "original_creation": current.get("creation") or row.get("creation"),
            "amendment_count": amendment_count,
        }
    return root_info


def _get_linked_invoice_names(doctype, invoice_names, link_field, filters=None):
    if not invoice_names:
        return set()
    query_filters = dict(filters or {})
    query_filters[link_field] = ["in", invoice_names]
    rows = frappe.get_all(
        doctype,
        filters=query_filters,
        fields=[link_field],
        limit_page_length=0,
    )
    return {row.get(link_field) for row in rows or [] if row.get(link_field)}


def _build_list_metadata_context(doctype, rows):
    invoice_names = [row.get("name") for row in rows or [] if row.get("name")]
    active_children = _get_linked_invoice_names(
        doctype,
        invoice_names,
        "amended_from",
        {"docstatus": ["!=", 2]},
    )
    submitted_returns = _get_linked_invoice_names(
        doctype,
        invoice_names,
        "return_against",
        {"docstatus": 1},
    )
    closing_reference_field = "sales_invoice" if doctype == "Sales Invoice" else "pos_invoice"
    closed_invoices = _get_linked_invoice_names(
        "Sales Invoice Reference",
        invoice_names,
        closing_reference_field,
        {
            "parenttype": "POS Closing Shift",
            "parentfield": "pos_transactions",
            "docstatus": 1,
        },
    )
    closed_invoices.update(
        row.get("name")
        for row in rows or []
        if row.get("name")
        and (
            row.get("pos_closing_entry")
            or (doctype == "POS Invoice" and row.get("consolidated_invoice"))
        )
    )
    return {
        "root_info": _get_root_invoice_info_map(doctype, rows),
        "profile_settings": _get_profile_edit_settings(row.get("pos_profile") for row in rows or []),
        "active_children": active_children,
        "submitted_returns": submitted_returns,
        "closed_invoices": closed_invoices,
    }


# --- Tanami: a submitted invoice is editable only while its shift is the cashier's open shift ---


def _current_open_shift_name(pos_profile):
    """The session user's open shift on this profile (submitted, Open, no submitted closing)."""
    if not pos_profile:
        return None
    cache = getattr(frappe.local, "posa_current_open_shift", None)
    if cache is None:
        cache = frappe.local.posa_current_open_shift = {}
    key = (frappe.session.user, pos_profile)
    if key not in cache:
        shifts = frappe.get_all(
            "POS Opening Shift",
            filters={
                "user": frappe.session.user,
                "pos_profile": pos_profile,
                "docstatus": 1,
                "status": "Open",
            },
            pluck="name",
            order_by="period_start_date desc",
        )
        closed = set(
            frappe.get_all(
                "POS Closing Shift",
                filters={"pos_opening_shift": ["in", shifts], "docstatus": 1},
                pluck="pos_opening_shift",
            )
            if shifts
            else []
        )
        cache[key] = next((shift for shift in shifts if shift not in closed), None)
    return cache[key]


def _invoice_shift_fields(doc):
    """is_pos / opening shift of a list row that was fetched without them."""
    if doc.get("posa_pos_opening_shift") is not None and doc.get("is_pos") is not None:
        return cint(doc.get("is_pos")), doc.get("posa_pos_opening_shift")
    if not _has_column(doc.doctype, "posa_pos_opening_shift"):
        return cint(doc.get("is_pos")), None
    values = frappe.db.get_value(doc.doctype, doc.name, ["is_pos", "posa_pos_opening_shift"]) or (0, None)
    return cint(values[0]), values[1]


def _in_current_open_shift(doc):
    is_pos, shift = _invoice_shift_fields(doc)
    return bool(is_pos and shift and shift == _current_open_shift_name(doc.get("pos_profile")))


def get_submitted_invoice_edit_blockers(doc):
    """Submitted returns and payment entries that stand in the way of editing the invoice.

    `in_open_shift` marks the ones created in the cashier's open shift.
    """
    shift = _current_open_shift_name(doc.get("pos_profile"))
    blockers = []
    for row in frappe.get_all(
        doc.doctype,
        filters={"return_against": doc.name, "docstatus": 1},
        fields=["name", "grand_total", "posa_pos_opening_shift"],
        order_by="creation asc",
    ):
        blockers.append(
            {
                "kind": "return",
                "doctype": doc.doctype,
                "name": row.name,
                "amount": abs(flt(row.grand_total)),
                "in_open_shift": bool(shift and row.posa_pos_opening_shift == shift),
            }
        )
    for row in frappe.db.sql(
        """
        select pe.name, pe.reference_no, sum(per.allocated_amount) as amount
        from `tabPayment Entry Reference` per
        join `tabPayment Entry` pe on pe.name = per.parent
        where per.reference_doctype = %s and per.reference_name = %s and pe.docstatus = 1
        group by pe.name, pe.reference_no
        order by pe.creation asc
        """,
        (doc.doctype, doc.name),
        as_dict=True,
    ):
        blockers.append(
            {
                "kind": "payment",
                "doctype": "Payment Entry",
                "name": row.name,
                "amount": abs(flt(row.amount)),
                "in_open_shift": bool(shift and row.reference_no == shift),
            }
        )
    return blockers


def _has_stored_value_settlement(doc):
    if flt(doc.get("posa_redeemed_customer_credit") or 0) > 0:
        return True
    redemptions = doc.get("gift_card_redemptions") or []
    return bool(redemptions)


def get_submitted_invoice_edit_metadata(doc, list_context=None):
    list_context = list_context or {}
    root_info = (list_context.get("root_info") or {}).get(doc.name)
    if root_info is None:
        root_info = _get_root_invoice_info(doc.doctype, doc)

    profile_settings = (list_context.get("profile_settings") or {}).get(doc.get("pos_profile"))
    window_hours = (
        profile_settings.get("edit_window_hours")
        if profile_settings is not None
        else _get_edit_window_hours(doc.get("pos_profile"))
    )
    age_hours = _hours_since(root_info.get("original_creation"))
    can_edit = True
    reason = None
    in_open_shift = (
        cint(doc.get("docstatus")) == 1
        and not cint(doc.get("is_return"))
        and not doc.get("return_against")
        and _in_current_open_shift(doc)
    )
    blockers = get_submitted_invoice_edit_blockers(doc) if in_open_shift else []

    feature_enabled = (
        profile_settings.get("feature_enabled")
        if profile_settings is not None
        else _feature_enabled(doc.get("pos_profile"))
    )
    if not feature_enabled:
        can_edit = False
        reason = _("Submitted invoice editing is disabled for this POS Profile.")
    elif cint(doc.get("docstatus")) != 1:
        can_edit = False
        reason = _("Only submitted invoices can be edited.")
    elif cint(doc.get("is_return")):
        can_edit = False
        reason = _("Return invoices cannot be edited. Use the return workflow.")
    elif doc.get("return_against"):
        can_edit = False
        reason = _("Credit notes cannot be edited. Use the return workflow.")
    elif (
        doc.name in list_context.get("submitted_returns", set())
        if list_context
        else frappe.db.exists(doc.doctype, {"return_against": doc.name, "docstatus": 1})
    ):
        can_edit = False
        reason = _("This invoice already has a submitted return or credit note.")
    elif (
        doc.name in list_context.get("active_children", set())
        if list_context
        else _get_active_children(doc.doctype, doc.name)
    ):
        can_edit = False
        reason = _("This invoice has already been amended. Edit the latest amended invoice.")
    elif _edit_window_configured() and age_hours > window_hours:
        # Tanami: the open-shift rule below is the limit; hours count only when the
        # profile has such a setting (a shift here can stay open longer than a day)
        can_edit = False
        reason = _("This invoice is outside the {0}-hour edit window.").format(window_hours)
    elif not in_open_shift:
        can_edit = False
        reason = _("Only invoices of the currently open shift can be edited from the POS.")
    elif blockers:
        can_edit = False
        reason = _("Cancel the linked return or payment receipt before editing this invoice.")
    elif (
        doc.name in list_context.get("closed_invoices", set())
        if list_context
        else _is_closed_invoice(doc)
    ):
        can_edit = False
        reason = _("This invoice is already linked to a submitted POS closing shift.")
    elif _has_stored_value_settlement(doc):
        can_edit = False
        reason = _("Invoices settled with gift cards or customer credit are not editable here.")

    return {
        "can_edit_submitted_invoice": bool(can_edit),
        "edit_block_reason": reason,
        "edit_window_hours": window_hours if _edit_window_configured() else None,
        "edit_age_hours": age_hours,
        "edit_blockers": blockers,
        **root_info,
    }


def assert_submitted_invoice_edit_allowed(doc, pos_profile=None, company=None):
    profile_name = pos_profile or doc.get("pos_profile")
    assert_pos_profile_write_allowed(profile_name, company=company or doc.get("company"))
    if pos_profile and doc.get("pos_profile") and doc.get("pos_profile") != pos_profile:
        frappe.throw(_("Invoice {0} does not belong to POS Profile {1}.").format(doc.name, pos_profile))
    if company and doc.get("company") and doc.get("company") != company:
        frappe.throw(_("Invoice {0} does not belong to company {1}.").format(doc.name, company))

    metadata = get_submitted_invoice_edit_metadata(doc)
    if not metadata.get("can_edit_submitted_invoice"):
        frappe.throw(metadata.get("edit_block_reason") or _("This invoice cannot be edited."))
    return metadata


def _clear_child_identity(row):
    cleaned = {}
    for key, value in (row or {}).items():
        if key in CHILD_ID_FIELDS:
            continue
        cleaned[key] = value
    return cleaned


def _safe_child_rows(rows, allowed_fields):
    cleaned = []
    for row in rows or []:
        source = _clear_child_identity(row)
        target = {field: source.get(field) for field in allowed_fields if field in source}
        cleaned.append(target)
    return cleaned


def _item_rows_from_correction(original_doc, correction):
    original_by_name = {row.name: row.as_dict() for row in original_doc.get("items") or []}
    incoming_rows = correction.get("items")
    if not isinstance(incoming_rows, list):
        incoming_rows = [row.as_dict() for row in original_doc.get("items") or []]

    result = []
    for incoming in incoming_rows:
        source = {}
        original_name = incoming.get("name")
        if original_name and original_name in original_by_name:
            source.update(original_by_name[original_name])
        source.update(incoming)
        if not source.get("item_code") or flt(source.get("qty")) == 0:
            continue
        result.append(source)
    return _safe_child_rows(result, ITEM_EDITABLE_FIELDS)


def _payment_rows_from_correction(original_doc, correction):
    incoming_rows = correction.get("payments")
    if not isinstance(incoming_rows, list):
        incoming_rows = [row.as_dict() for row in original_doc.get("payments") or []]
    return [
        row
        for row in _safe_child_rows(incoming_rows, PAYMENT_EDITABLE_FIELDS)
        if row.get("mode_of_payment")
    ]


def build_submitted_invoice_amendment_payload(original_doc, correction_data=None, client_request_id=None):
    correction = _loads(correction_data, {})
    amended_doc = frappe.copy_doc(original_doc)
    amended = amended_doc.as_dict()
    amended["doctype"] = original_doc.doctype
    amended["_force_invoice_doctype"] = original_doc.doctype
    amended["amended_from"] = original_doc.name
    amended["docstatus"] = 0
    amended.pop("name", None)
    amended.pop("status", None)
    amended.pop("pos_closing_entry", None)
    amended.pop("consolidated_invoice", None)
    amended["is_return"] = 0
    amended["return_against"] = None
    amended["pos_profile"] = original_doc.get("pos_profile")
    amended["company"] = original_doc.get("company")

    for fieldname in TOP_LEVEL_EDITABLE_FIELDS:
        if fieldname in correction:
            amended[fieldname] = correction.get(fieldname)

    # Tanami: another customer on the corrected invoice brings its own name, receivable
    # account, address and contact; whatever was copied from the old customer is dropped
    # so that set_missing_values fills it in again
    if amended.get("customer") and amended.get("customer") != original_doc.get("customer"):
        if not frappe.db.exists("Customer", {"name": amended["customer"], "disabled": 0}):
            frappe.throw(_("Customer {0} was not found.").format(amended["customer"]))
        for fieldname in CUSTOMER_DEPENDENT_FIELDS:
            amended.pop(fieldname, None)

    amended["items"] = _item_rows_from_correction(original_doc, correction)
    amended["payments"] = _payment_rows_from_correction(original_doc, correction)

    if doctype_supports_client_request_id(original_doc.doctype):
        amended["posa_client_request_id"] = client_request_id or f"submitted-edit-{uuid.uuid4()}"

    return amended


def _preview_amended_doc(original_doc, correction_data=None):
    payload = build_submitted_invoice_amendment_payload(original_doc, correction_data)
    preview_doc = frappe.get_doc(payload)
    preview_doc.flags.ignore_permissions = True
    if hasattr(preview_doc, "set_missing_values"):
        preview_doc.set_missing_values()
        _reapply_incoming_payment_amounts(preview_doc, payload.get("payments") or [])
    if hasattr(preview_doc, "calculate_taxes_and_totals"):
        preview_doc.calculate_taxes_and_totals()
    return preview_doc


@frappe.whitelist()
def list_submitted_invoices(
    doctype="Sales Invoice",
    filters=None,
    fields=None,
    order_by="posting_date desc, posting_time desc, modified desc",
    limit_page_length=0,
    pos_profile=None,
    company=None,
):
    doctype = _normalize_doctype(doctype)
    filters = _loads(filters, {})
    fields = _loads(fields, [])
    if not isinstance(filters, dict):
        frappe.throw(_("Invalid filters for submitted invoice list."))
    if not isinstance(fields, list) or not fields:
        fields = ["name", "customer", "posting_date", "grand_total", "status"]

    filters["docstatus"] = 1
    if pos_profile:
        filters["pos_profile"] = pos_profile
    if company:
        filters["company"] = company

    metadata_fields = [
        "name",
        "docstatus",
        "is_return",
        "return_against",
        "creation",
        "amended_from",
        "pos_profile",
        "company",
        "is_pos",
    ]
    if _has_column(doctype, "posa_pos_opening_shift"):
        metadata_fields.append("posa_pos_opening_shift")
    if _has_column(doctype, "pos_closing_entry"):
        metadata_fields.append("pos_closing_entry")
    if doctype == "POS Invoice":
        metadata_fields.append("consolidated_invoice")

    requested_fields = list(dict.fromkeys([*fields, *metadata_fields]))
    rows = frappe.get_list(
        doctype,
        filters=filters,
        fields=requested_fields,
        order_by=order_by,
        limit_page_length=cint(limit_page_length or 0),
    )
    list_context = _build_list_metadata_context(doctype, rows)
    for row in rows or []:
        row["doctype"] = doctype
        doc = frappe._dict(row)
        row.update(get_submitted_invoice_edit_metadata(doc, list_context=list_context))
        # Tanami: sales and returns of the open shift can be cancelled from the POS
        row["can_cancel_from_pos"] = bool(_in_current_open_shift(doc))
    return rows


@frappe.whitelist()
def get_submitted_invoice_for_edit(doctype, name, pos_profile=None, company=None):
    doctype = _normalize_doctype(doctype)
    doc = frappe.get_doc(doctype, name)
    metadata = assert_submitted_invoice_edit_allowed(doc, pos_profile=pos_profile, company=company)
    return {"invoice": doc.as_dict(), "metadata": metadata}


@frappe.whitelist()
def get_submitted_invoice_edit_item_price(doctype, name, item_code, pos_profile=None, company=None):
    """Tanami: selling price list rate of an item being added to an invoice under edit."""
    from erpnext.stock.get_item_details import get_price_list_rate_for

    doctype = _normalize_doctype(doctype)
    doc = frappe.get_doc(doctype, name)
    assert_submitted_invoice_edit_allowed(doc, pos_profile=pos_profile, company=company)
    item = frappe.db.get_value(
        "Item", {"name": item_code, "disabled": 0}, ["name", "item_name", "stock_uom"], as_dict=True
    )
    if not item:
        return {}
    args = frappe._dict(
        price_list=doc.get("selling_price_list"),
        customer=doc.get("customer"),
        uom=item.stock_uom,
        stock_uom=item.stock_uom,
        transaction_date=frappe.utils.nowdate(),
        qty=1,
        conversion_factor=1,
    )
    return {
        "item_code": item.name,
        "item_name": item.item_name,
        "price_list_rate": flt(get_price_list_rate_for(args, item.name)),
    }


@frappe.whitelist()
def search_submitted_invoice_edit_items(doctype, name, search=None, pos_profile=None, company=None, limit=20):
    """Tanami: items whose code, name or barcode contains the text typed into the add-item row."""
    doctype = _normalize_doctype(doctype)
    doc = frappe.get_doc(doctype, name)
    assert_submitted_invoice_edit_allowed(doc, pos_profile=pos_profile, company=company)
    search = str(search or "").strip()
    words = search.split()[:6]
    if not words:
        return []

    def like(text):
        return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    conditions = []
    values = []
    for word in words:
        pattern = f"%{like(word)}%"
        conditions.append(
            """(item.name like %s or item.item_name like %s or exists (
                select 1 from `tabItem Barcode` barcode
                where barcode.parent = item.name and barcode.barcode like %s))"""
        )
        values.extend([pattern, pattern, pattern])
    values.extend([search, f"{like(search)}%", min(max(cint(limit), 1), 50)])
    return frappe.db.sql(
        f"""
        select item.name as item_code, item.item_name, item.stock_uom
        from `tabItem` item
        where item.disabled = 0 and item.is_sales_item = 1 and item.has_variants = 0
            and {" and ".join(conditions)}
        order by (item.name = %s) desc, (item.name like %s) desc, item.item_name
        limit %s
        """,
        values,
        as_dict=True,
    )


@frappe.whitelist()
def preview_submitted_invoice_edit(doctype, name, correction_data=None, pos_profile=None, company=None):
    doctype = _normalize_doctype(doctype)
    doc = frappe.get_doc(doctype, name)
    metadata = assert_submitted_invoice_edit_allowed(doc, pos_profile=pos_profile, company=company)
    preview_doc = _preview_amended_doc(doc, correction_data)
    return {"invoice": preview_doc.as_dict(), "metadata": metadata}


@frappe.whitelist()
def submit_submitted_invoice_edit(
    doctype,
    name,
    correction_data=None,
    client_request_id=None,
    pos_profile=None,
    company=None,
):
    from posawesome.posawesome.api.pos_access import get_authorized_pos_profile

    doctype = _normalize_doctype(doctype)
    client_request_id = (client_request_id or "").strip() or f"submitted-edit-{uuid.uuid4()}"
    scoped_original = frappe.get_doc(doctype, name)
    profile_doc = get_authorized_pos_profile(
        pos_profile or scoped_original.get("pos_profile"),
        company=company or scoped_original.get("company"),
    )
    canonical_profile = profile_doc.get("name")
    canonical_company = profile_doc.get("company")
    if (
        scoped_original.get("pos_profile") != canonical_profile
        or scoped_original.get("company") != canonical_company
    ):
        frappe.throw(_("This invoice is not available for the selected POS Profile."))
    scoped_original.check_permission("read")

    existing = find_invoice_by_client_request_id(
        client_request_id,
        preferred_doctype=doctype,
        pos_profile=canonical_profile,
        company=canonical_company,
        permission_type="read",
    )
    if existing and existing.get("amended_from") == name and cint(existing.docstatus) == 1:
        return {
            "name": existing.name,
            "doctype": existing.doctype,
            "docstatus": existing.docstatus,
            "idempotent": True,
            "metadata": get_submitted_invoice_edit_metadata(existing),
        }

    savepoint = "submitted_invoice_edit"
    frappe.db.savepoint(savepoint)
    try:
        frappe.db.sql(f"select name from `tab{doctype}` where name=%s for update", name)
        original_doc = frappe.get_doc(doctype, name)
        metadata = assert_submitted_invoice_edit_allowed(
            original_doc,
            pos_profile=pos_profile,
            company=company,
        )
        payload = build_submitted_invoice_amendment_payload(
            original_doc,
            correction_data=correction_data,
            client_request_id=client_request_id,
        )
        submission_data = {"client_request_id": client_request_id}
        with trusted_invoice_shift_reassignment(
            payload,
            submission_data,
            "submitted_amendment",
        ):
            original_doc.flags.ignore_permissions = True
            frappe.flags.ignore_account_permission = True
            original_doc.cancel()

            # Tanami: not submit_invoice(), whose deadlock retry rolls the whole
            # transaction back (undoing the cancellation) and replays only the submit
            response = _submit_invoice_once(
                json.dumps(payload, default=str),
                json.dumps(submission_data, default=str),
                submit_in_background=False,
            )
        amended_doc = frappe.get_doc(response.get("doctype") or doctype, response.get("name"))
        set_invoice_client_request_id(amended_doc, client_request_id)
        amended_doc.db_update()
        return {
            **response,
            "original_invoice": name,
            "idempotent": True,
            "metadata": {
                **metadata,
                **get_submitted_invoice_edit_metadata(amended_doc),
            },
        }
    except Exception:
        try:
            frappe.db.rollback(save_point=savepoint)
        except Exception:
            # the savepoint is gone when the database already rolled the transaction back
            frappe.db.rollback()
        raise


@frappe.whitelist()
def cancel_submitted_invoice_edit_blocker(
    doctype,
    name,
    blocker_doctype,
    blocker_name,
    pos_profile=None,
    company=None,
):
    """Tanami: cancel a return or payment receipt of the open shift so its invoice can be edited.

    Requested by the owner (requirements 11.9): the cashier has no general Cancel
    permission; what authorizes this is the POS scope, checked here: write access to the
    profile, the invoice in the cashier's own open shift, and the linked document created
    in that same shift. Anything from a closed shift stays with management on the desk.
    """
    doctype = _normalize_doctype(doctype)
    doc = frappe.get_doc(doctype, name)
    profile_name = pos_profile or doc.get("pos_profile")
    assert_pos_profile_write_allowed(profile_name, company=company or doc.get("company"))
    if doc.get("pos_profile") != profile_name:
        frappe.throw(_("Invoice {0} does not belong to POS Profile {1}.").format(doc.name, profile_name))
    doc.check_permission("read")
    if not _feature_enabled(profile_name):
        frappe.throw(_("Submitted invoice editing is disabled for this POS Profile."))
    if cint(doc.docstatus) != 1 or cint(doc.get("is_return")) or not _in_current_open_shift(doc):
        frappe.throw(_("Only invoices of the currently open shift can be edited from the POS."))

    blocker = next(
        (
            row
            for row in get_submitted_invoice_edit_blockers(doc)
            if row["doctype"] == blocker_doctype and row["name"] == blocker_name
        ),
        None,
    )
    if not blocker:
        frappe.throw(_("{0} is not linked to invoice {1}.").format(blocker_name, doc.name))
    if not blocker["in_open_shift"]:
        frappe.throw(
            _("{0} belongs to another shift and can only be cancelled by management.").format(blocker_name)
        )

    linked_doc = frappe.get_doc(blocker["doctype"], blocker["name"])
    linked_doc.flags.ignore_permissions = True
    frappe.flags.ignore_account_permission = True
    linked_doc.cancel()

    doc.reload()
    return {
        "cancelled": blocker["name"],
        "metadata": get_submitted_invoice_edit_metadata(doc),
    }
