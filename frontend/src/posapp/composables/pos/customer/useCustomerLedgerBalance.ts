/**
 * Tanami: ledger balance of the selected customer, shared by the bar under the customer
 * field and the "balance after invoice" line of the payment dialog. The figure comes from
 * the same server calculation as the balance box printed on the invoice.
 */
import { reactive } from "vue";

declare const frappe: any;
declare const __: (_text: string, _args?: any[]) => string;

export const customerLedgerBalance = reactive({
	customer: "" as string,
	balance: 0,
	isCashCustomer: false,
	loading: false,
	available: false,
});

let requestSeq = 0;

export async function refreshCustomerLedgerBalance(
	customer?: string | null,
	company?: string | null,
	excludeVoucher?: string | null,
) {
	const seq = ++requestSeq;
	customerLedgerBalance.customer = customer || "";
	customerLedgerBalance.available = false;
	if (!customer) {
		customerLedgerBalance.balance = 0;
		customerLedgerBalance.isCashCustomer = false;
		customerLedgerBalance.loading = false;
		return;
	}
	customerLedgerBalance.loading = true;
	try {
		const r = await frappe.call({
			method: "tanami_workshop.pos_rules.get_pos_customer_balance",
			args: { customer, company: company || undefined, exclude_voucher: excludeVoucher || undefined },
		});
		if (seq !== requestSeq) return;
		customerLedgerBalance.balance = Number(r?.message?.balance || 0);
		customerLedgerBalance.isCashCustomer = Boolean(r?.message?.is_cash_customer);
		customerLedgerBalance.available = true;
	} catch (error) {
		if (seq !== requestSeq) return;
		console.warn("Unable to load customer balance", error);
	} finally {
		if (seq === requestSeq) customerLedgerBalance.loading = false;
	}
}

/** `1,250.000 د.ل — مدين`: the direction replaces the minus sign. */
export function describeLedgerBalance(amount: number, currency?: string | null) {
	const value = Math.round((Number(amount) || 0) * 1000) / 1000;
	const figure = Math.abs(value).toLocaleString("en-US", {
		minimumFractionDigits: 3,
		maximumFractionDigits: 3,
	});
	const symbol =
		(currency && typeof (window as any).get_currency_symbol === "function"
			? (window as any).get_currency_symbol(currency)
			: "") ||
		currency ||
		"";
	const tone = value > 0 ? "debit" : value < 0 ? "credit" : "zero";
	const direction = value > 0 ? __("Debit") : value < 0 ? __("Credit") : "";
	return { figure, symbol, tone, direction };
}
