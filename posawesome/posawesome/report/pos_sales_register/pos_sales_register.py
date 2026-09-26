# Copyright (c) 2025, POS Awesome and contributors
# License: GPLv3
# Report: Pos Sales Register (POS Awesome module)

import frappe
from frappe import _
from frappe.utils import flt

ROUNDED_TOTAL_COL_IDX = 4


def execute(filters=None):
    filters = filters or {}
    conditions, params = _build_conditions(filters)

    query = f"""
        SELECT
            si.name AS "Sales Invoice:Link/Sales Invoice:120",
            si.posting_date AS "Posting Date:Date:100",
            si.customer AS "Customer:Link/Customer:150",
            si.customer_name AS "Customer Name:Data:150",
            IF(COALESCE(si.disable_rounded_total, 0) = 1, si.grand_total, COALESCE(NULLIF(si.rounded_total, 0), si.grand_total)) AS "Rounded Total:Currency:120",
            si.currency AS "Currency:Link/Currency:80",
            si.posa_pos_opening_shift AS "POS Opening Shift:Link/POS Opening Shift:150",
            os.pos_closing_shift AS "POS Closing Shift:Link/POS Closing Shift:150",
            GROUP_CONCAT(DISTINCT sip.mode_of_payment ORDER BY sip.mode_of_payment SEPARATOR ', ') AS "Mode of Payment:Data:180"
        FROM `tabSales Invoice` si
        LEFT JOIN `tabPOS Opening Shift` os ON os.name = si.posa_pos_opening_shift
        LEFT JOIN `tabPOS Closing Shift` cs ON cs.name = os.pos_closing_shift
        LEFT JOIN `tabSales Invoice Payment` sip ON sip.parent = si.name
        WHERE si.docstatus = 1
            AND si.is_pos = 1
            {conditions}
        GROUP BY si.name, si.posting_date, si.customer, si.customer_name, si.grand_total, si.rounded_total, si.disable_rounded_total, si.currency, si.posa_pos_opening_shift, os.pos_closing_shift
        ORDER BY si.posting_date DESC, si.creation DESC
    """

    result = list(frappe.db.sql(query, params, as_dict=0))
    columns = _get_columns()
    if result:
        total_rounded = round(flt(sum(flt(row[ROUNDED_TOTAL_COL_IDX]) for row in result)), 2)
        total_row = [""] * len(columns)
        total_row[0] = _("Total")
        total_row[ROUNDED_TOTAL_COL_IDX] = total_rounded
        result.append(total_row)
    return columns, result


def _get_columns():
    return [
        "Sales Invoice:Link/Sales Invoice:120",
        "Posting Date:Date:100",
        "Customer:Link/Customer:150",
        "Customer Name:Data:150",
        "Rounded Total:Currency:120",
        "Currency:Link/Currency:80",
        "POS Opening Shift:Link/POS Opening Shift:150",
        "POS Closing Shift:Link/POS Closing Shift:150",
        "Mode of Payment:Data:180",
    ]


def _build_conditions(filters):
    conditions = []
    params = {}
    if filters.get("from_date"):
        conditions.append("AND si.posting_date >= %(from_date)s")
        params["from_date"] = filters["from_date"]
    if filters.get("to_date"):
        conditions.append("AND si.posting_date <= %(to_date)s")
        params["to_date"] = filters["to_date"]
    if filters.get("sales_invoice"):
        conditions.append("AND si.name = %(sales_invoice)s")
        params["sales_invoice"] = filters["sales_invoice"]
    if filters.get("customer"):
        conditions.append("AND si.customer = %(customer)s")
        params["customer"] = filters["customer"]
    if filters.get("customer_name"):
        conditions.append("AND si.customer_name LIKE %(customer_name)s")
        params["customer_name"] = "%" + filters["customer_name"] + "%"
    if filters.get("grand_total_min") is not None and filters.get("grand_total_min") != "":
        conditions.append("AND si.grand_total >= %(grand_total_min)s")
        params["grand_total_min"] = flt(filters["grand_total_min"])
    if filters.get("grand_total_max") is not None and filters.get("grand_total_max") != "":
        conditions.append("AND si.grand_total <= %(grand_total_max)s")
        params["grand_total_max"] = flt(filters["grand_total_max"])
    if filters.get("currency"):
        conditions.append("AND si.currency = %(currency)s")
        params["currency"] = filters["currency"]
    if filters.get("pos_opening_shift"):
        conditions.append("AND si.posa_pos_opening_shift = %(pos_opening_shift)s")
        params["pos_opening_shift"] = filters["pos_opening_shift"]
    if filters.get("pos_closing_shift"):
        conditions.append("AND os.pos_closing_shift = %(pos_closing_shift)s")
        params["pos_closing_shift"] = filters["pos_closing_shift"]
    if filters.get("mode_of_payment"):
        conditions.append("AND sip.mode_of_payment = %(mode_of_payment)s")
        params["mode_of_payment"] = filters["mode_of_payment"]
    condition_sql = "\n\t\t\t".join(conditions) if conditions else ""
    return condition_sql, params
