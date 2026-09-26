import frappe


CUSTOM_FIELD_NAME = "Item Barcode-posa_uom"


def execute():
    if not frappe.db.exists("Custom Field", CUSTOM_FIELD_NAME):
        return

    # Carry legacy barcode UOMs over to ERPNext's standard field before dropping the custom one
    if frappe.db.has_column("Item Barcode", "posa_uom") and frappe.db.has_column("Item Barcode", "uom"):
        frappe.db.sql(
            """
            UPDATE `tabItem Barcode`
            SET uom = posa_uom
            WHERE IFNULL(posa_uom, '') != '' AND IFNULL(uom, '') = ''
            """
        )

    frappe.delete_doc("Custom Field", CUSTOM_FIELD_NAME, ignore_permissions=True, force=True)
    frappe.clear_cache(doctype="Item Barcode")
