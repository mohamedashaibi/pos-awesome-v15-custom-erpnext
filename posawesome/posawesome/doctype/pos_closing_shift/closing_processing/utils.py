import frappe
from frappe.utils import flt


def get_base_value(doc, fieldname, base_fieldname=None, conversion_rate=None):
    """Return the value for a field in company currency."""

    base_fieldname = base_fieldname or f"base_{fieldname}"
    base_value = doc.get(base_fieldname)

    if base_value not in (None, ""):
        return flt(base_value)

    value = doc.get(fieldname)
    if value in (None, ""):
        return 0

    if conversion_rate is None:
        conversion_rate = (
            doc.get("conversion_rate")
            or doc.get("source_exchange_rate")
            or doc.get("target_exchange_rate")
            or doc.get("exchange_rate")
            or 1
        )

    return flt(value) * flt(conversion_rate or 1)


def get_cash_account(cash_mode_of_payment, company):
    """Return the ledger account of the cash mode of payment for the company."""

    if not cash_mode_of_payment or not company:
        return None

    return frappe.db.get_value(
        "Mode of Payment Account",
        {"parent": cash_mode_of_payment, "company": company},
        "default_account",
    )


def change_reduces_cash(invoice, cash_account):
    """Whether the invoice change was handed back from the cash drawer.

    Change booked to any other account (e.g. a POS adjustments account) never
    left the drawer, so it must not reduce the expected cash amount.
    """

    change_account = invoice.get("account_for_change_amount")
    if not cash_account or not change_account:
        return True

    return change_account == cash_account
