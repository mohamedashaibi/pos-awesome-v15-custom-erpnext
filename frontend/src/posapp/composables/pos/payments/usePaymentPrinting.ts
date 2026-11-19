import { unref, type Ref } from "vue";
import renderOfflineInvoiceHTML from "../../../../offline_print_template";
import {
	appendDebugPrintParam,
	isDebugPrintEnabled,
	printHtmlDocument,
	silentPrint,
	watchPrintWindow,
} from "../../../plugins/print";
import { printHtmlViaQz } from "../../../services/qzTray";
import {
	confirmDocumentPrintFallback,
	printDocumentViaConfiguredQz,
	shouldUseConfiguredQzDocumentPrinting,
	shouldUseRawDocumentPrinting,
} from "../../../services/documentPrint";
import { isOffline } from "../../../../offline/index";
import { resolvePaymentPrintDoctype } from "../../../utils/paymentPrintDoctype";
import {
	isExchangeReceiptDocument,
	printExchangeReceipt,
} from "../../../services/exchangeReceiptPrint";

declare const frappe: any;

export interface PaymentPrintingOptions {
	invoiceDoc: Ref<any>;
	posProfile: Ref<any>;
	invoiceType: Ref<string>;
	printFormat?: Ref<string>;
}

export function usePaymentPrinting(options: PaymentPrintingOptions) {
	const { invoiceDoc, posProfile, invoiceType, printFormat } = options;

	const resolveDocumentName = (value: any) => {
		if (value === null || value === undefined) {
			return "";
		}
		const name = String(value).trim();
		return name && name !== "undefined" && name !== "null" ? name : "";
	};

	const resolvePrintContext = (input: { doc?: any; doctype?: string } = {}) => {
		const doc = input.doc || unref(invoiceDoc);
		const profile = unref(posProfile);
		const type = unref(invoiceType);
		const pFormatOverride = unref(printFormat);
		const print_format =
			pFormatOverride ||
			profile.print_format_for_online ||
			profile.print_format;
		const letter_head = profile.letter_head || 0;
		const doctype = resolvePaymentPrintDoctype({
			profile,
			invoiceType: type,
			explicitDoctype: input.doctype || input.doc?.doctype,
		});

		return {
			doc,
			profile,
			doctype,
			print_format,
			letter_head,
		};
	};

	const openOfflineInvoicePreview = async (
		invoice: any,
		{ debugPrint = false, printFormatStr = "" } = {},
	) => {
		if (!invoice) return;
		const html = await renderOfflineInvoiceHTML(invoice);
		const win = window.open("", "_blank");
		if (!win) return;
		win.document.write(html);
		win.document.close();
		win.focus();
		if (debugPrint) {
			console.log("[POSAwesome][Print Debug]", {
				location: win.location?.href || null,
				online: navigator.onLine,
				trigger_print: "0",
				print_format: printFormatStr || null,
				template_path: "offline-fallback",
				should_print: false,
			});
		}
	};

	const printOfflineInvoice = async (invoice: any) => {
		if (!invoice) return;
		const html = await renderOfflineInvoiceHTML(invoice);
		const win = window.open("", "_blank");
		if (!win) return;
		win.document.write(html);
		win.document.close();
		win.focus();
		win.print();
	};

	/**
	 * Tanami: print the receipt from the invoice as it stands on screen, without waiting
	 * for the background submission. The server only renders the print format from the
	 * data sent; the invoice number is the one of the saved draft.
	 */
	const printFromScreenData = async (context: ReturnType<typeof resolvePrintContext>, docname: string) => {
		const { doc, profile, doctype, print_format } = context;
		const response = await frappe.call({
			method: "frappe.www.printview.get_html_and_style",
			args: {
				doc: JSON.stringify({ ...doc, doctype, name: docname, docstatus: 0, posa_is_printed: 1 }),
				print_format: print_format || "Standard",
				no_letterhead: 1,
			},
		});
		const body = response?.message?.html;
		if (!body) {
			throw new Error("Unable to load print HTML from server.");
		}
		const bundle = frappe.assets?.bundled_asset?.("print.bundle.css");
		const rtl = frappe.utils?.is_rtl?.();
		const html = `<!DOCTYPE html>
<html lang="${frappe.boot?.lang || "ar"}" dir="${rtl ? "rtl" : "ltr"}">
<head>
<meta charset="utf-8">
${bundle ? `<link rel="stylesheet" href="${bundle}">` : ""}
<style>${response.message.style || ""}</style>
</head>
<body><div class="print-format-gutter"><div class="print-format">${body}</div></div></body>
</html>`;
		if (shouldUseConfiguredQzDocumentPrinting(profile) && !shouldUseRawDocumentPrinting(profile)) {
			await printHtmlViaQz(html, { widthMm: 148 });
			return;
		}
		await printHtmlDocument(html);
	};

	const loadPrintPage = async (
		input: { doc?: any; doctype?: string; name?: string; fromScreen?: boolean } = {},
	) => {
		const { doc, profile, doctype, print_format, letter_head } = resolvePrintContext(input);
		if (isExchangeReceiptDocument(doc)) {
			await printExchangeReceipt(doc, profile);
			return;
		}
		if (input.fromScreen && !isOffline()) {
			const screenName = resolveDocumentName(input.name || doc?.name);
			if (!screenName) {
				throw new Error("Cannot print document without a document name");
			}
			await printFromScreenData(resolvePrintContext(input), screenName);
			return;
		}
		const debugPrint = isDebugPrintEnabled();
		const offline = isOffline();
		const docname = resolveDocumentName(input.name || doc?.name);

		if (!docname && !offline) {
			throw new Error("Cannot print document without a submitted document name");
		}

		// Keep printview auto-trigger disabled; watchPrintWindow/silentPrint owns
		// the single browser print call so submit-and-print does not prompt twice.
		let url =
			frappe.urllib.get_base_url() +
			"/printview?doctype=" +
			encodeURIComponent(doctype) +
			"&name=" +
			encodeURIComponent(docname) +
			"&trigger_print=0" +
			"&format=" +
			encodeURIComponent(print_format || "Standard") +
			"&no_letterhead=" +
			letter_head;

		url = appendDebugPrintParam(url, debugPrint);

		const printOptions = {
			invoiceDoc: doc,
			allowOfflineFallback: isOffline(),
			triggerPrint: "1",
			debugPrint,
			debugInfo: {
				printFormat: print_format,
				templatePath: "online-printview",
			},
		};

		const useRawPrint = shouldUseRawDocumentPrinting(profile);
		const useConfiguredQzPrint = shouldUseConfiguredQzDocumentPrinting(profile);

		if (profile.posa_open_print_in_new_tab && !useRawPrint) {
			if (offline) {
				openOfflineInvoicePreview(doc, {
					debugPrint,
					printFormatStr: print_format,
				});
				return;
			}
			let newTabUrl =
				frappe.urllib.get_base_url() +
				"/printview?doctype=" +
				encodeURIComponent(doctype) +
				"&name=" +
				encodeURIComponent(docname) +
				"&trigger_print=0" +
				"&format=" +
				encodeURIComponent(print_format || "Standard");

			if (profile.letter_head) {
				newTabUrl +=
					"&letterhead=" + encodeURIComponent(profile.letter_head);
				newTabUrl += "&no_letterhead=0";
			} else {
				newTabUrl += "&no_letterhead=0";
			}

			newTabUrl = appendDebugPrintParam(newTabUrl, debugPrint);
			const printWindow = window.open(newTabUrl, "_blank");
			if (printWindow) {
				watchPrintWindow(printWindow, {
					...printOptions,
					triggerPrint: "0",
					shouldPrint: false,
				});
			}
			return;
		}

		if (useConfiguredQzPrint) {
			if (!offline) {
				try {
					await printDocumentViaConfiguredQz({
						doctype,
						name: docname,
						doc,
						profile,
						printFormat: print_format || "Standard",
						letterhead: profile.letter_head || null,
						noLetterhead: letter_head,
					});
					return;
				} catch (error) {
					console.warn("QZ Tray print failed", error);
					if (confirmDocumentPrintFallback(error, { raw: useRawPrint })) {
						silentPrint(url, printOptions);
					}
					return;
				}
			}
			if (useRawPrint) {
				const offlineError = new Error("Raw printing is not available while the POS is offline.");
				if (confirmDocumentPrintFallback(offlineError, { raw: true, offline: true })) {
					silentPrint(url, printOptions);
				}
				return;
			}
			silentPrint(url, printOptions);
		} else {
			silentPrint(url, printOptions);
		}
	};

	return {
		loadPrintPage,
		printOfflineInvoice,
		openOfflineInvoicePreview,
	};
}
