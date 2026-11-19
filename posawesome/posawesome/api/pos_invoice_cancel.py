"""Tanami: cancelling a sales or return invoice of the open shift from the POS screen.

The cashier has no general Cancel permission. What authorizes the cancellation is the
POS scope checked here: write access to the profile and an invoice that belongs to the
cashier's own open shift. Once the shift is closed the button is gone and cancelling
stays with management on the desk.
"""

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from posawesome.posawesome.api.submitted_invoice_edits import (
    _current_open_shift_name,
    _has_column,
    _in_current_open_shift,
    _normalize_doctype,
    get_submitted_invoice_edit_blockers,
)
from posawesome.posawesome.api.utils import assert_pos_profile_write_allowed

CANCEL_FIELDS = ("ws_cancel_reason", "ws_cancelled_by", "ws_cancelled_on")
LIST_FIELDS = (
    "name",
    "customer",
    "customer_name",
    "posting_date",
    "posting_time",
    "grand_total",
    "paid_amount",
    "change_amount",
    "outstanding_amount",
    "currency",
    "pos_profile",
    "owner",
    "modified_by",
    "is_return",
    "return_against",
)


def can_cancel_from_pos(doc):
    """A submitted POS invoice (sale or return) of the session user's open shift."""
    return cint(doc.get("docstatus")) == 1 and _in_current_open_shift(doc)


def _change_payment_entries(doc):
    """Change / customer-credit payment entries created together with the invoice."""
    if not _has_column("Payment Entry", "ws_source_invoice"):
        return []
    return frappe.get_all(
        "Payment Entry",
        filters={"ws_source_invoice": doc.name, "docstatus": 1},
        pluck="name",
        order_by="creation desc",
    )


@frappe.whitelist()
def cancel_invoice_from_pos(doctype, name, reason=None, pos_profile=None, company=None):
    doctype = _normalize_doctype(doctype)
    reason = (reason or "").strip()
    if not reason:
        frappe.throw(_("Cancellation reason is required"))

    frappe.db.sql(f"select name from `tab{doctype}` where name=%s for update", name)
    doc = frappe.get_doc(doctype, name)
    profile_name = pos_profile or doc.get("pos_profile")
    assert_pos_profile_write_allowed(profile_name, company=company or doc.get("company"))
    if doc.get("pos_profile") != profile_name:
        frappe.throw(_("Invoice {0} does not belong to POS Profile {1}.").format(doc.name, profile_name))
    doc.check_permission("read")
    if cint(doc.docstatus) == 2:
        frappe.throw(_("Invoice {0} is already cancelled").format(doc.name))
    if not can_cancel_from_pos(doc):
        frappe.throw(_("Only invoices of the currently open shift can be cancelled from the POS."))

    # change handed back or kept as customer credit when the invoice was paid goes with it
    change_entries = _change_payment_entries(doc)
    if not cint(doc.get("is_return")):
        blockers = get_submitted_invoice_edit_blockers(doc)
        returns = [row["name"] for row in blockers if row["kind"] == "return"]
        if returns:
            frappe.throw(_("Return invoice {0} must be cancelled first").format(", ".join(returns)))
        receipts = [
            row["name"] for row in blockers if row["kind"] == "payment" and row["name"] not in change_entries
        ]
        if receipts:
            frappe.throw(_("Payment receipt {0} must be cancelled first").format(", ".join(receipts)))

    frappe.flags.ignore_account_permission = True
    for payment_entry in change_entries:
        entry = frappe.get_doc("Payment Entry", payment_entry)
        entry.flags.ignore_permissions = True
        entry.cancel()

    doc.flags.ignore_permissions = True
    doc.cancel()

    values = {
        "ws_cancel_reason": reason,
        "ws_cancelled_by": frappe.session.user,
        "ws_cancelled_on": now_datetime(),
    }
    values = {field: value for field, value in values.items() if _has_column(doctype, field)}
    if values:
        frappe.db.set_value(doctype, doc.name, values, update_modified=False)
    doc.add_comment("Info", _("Cancelled from the POS by {0}. Reason: {1}").format(frappe.session.user, reason))
    return {"cancelled": doc.name, "is_return": cint(doc.get("is_return"))}


@frappe.whitelist()
def list_cancelled_invoices(doctype="Sales Invoice", pos_profile=None, company=None):
    """Invoices of the open shift cancelled from the POS, shown in the lists with a Cancelled tag."""
    doctype = _normalize_doctype(doctype)
    assert_pos_profile_write_allowed(pos_profile, company=company)
    shift = _current_open_shift_name(pos_profile)
    if not shift or not _has_column(doctype, "ws_cancel_reason"):
        return []
    rows = frappe.get_all(
        doctype,
        filters={
            "docstatus": 2,
            "pos_profile": pos_profile,
            "posa_pos_opening_shift": shift,
            "ws_cancel_reason": ["is", "set"],
        },
        fields=[*LIST_FIELDS, *CANCEL_FIELDS],
        order_by="posting_date desc, posting_time desc, modified desc",
        limit_page_length=0,
    )
    for row in rows:
        row.update({"doctype": doctype, "docstatus": 2, "status": "Cancelled", "is_cancelled": 1})
    return rows
