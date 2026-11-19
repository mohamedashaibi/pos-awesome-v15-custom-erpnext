import { describe, expect, it } from "vitest";

import { useItemsSearch } from "../src/posapp/composables/pos/items/store/useItemsSearch";
import { useItemSearch } from "../src/posapp/composables/pos/items/useItemSearch";
import {
	normalizeSearchText,
	tokenizeSearchText,
} from "../src/posapp/utils/searchText";

const catalog = () =>
	[
		{ item_code: "I-0326", item_name: "طابة صندوق  بيج ( 4 ) " },
		{ item_code: "I-0325", item_name: "باكيتة صندوق بيج ( 4 ) " },
		{ item_code: "I-0324", item_name: "زاوية صندوق تجميع بيج" },
		{ item_code: "I-0219", item_name: "طابه صندوق قنتشي" },
		{ item_code: "I-0151", item_name: "زاوية صندوق تجميع رصاصي" },
		{ item_code: "164", item_name: "سيخ مجرى قندشي ( 3-67 )" },
		{ item_code: "I-0164", item_name: " مفصل باب ( 4 )" },
		{
			item_code: "I-0500",
			item_name: "قفل أبواب",
			item_barcode: [{ barcode: "6281000000017" }],
		},
	] as any[];

const search = (term: string) => {
	const store = useItemsSearch();
	const items = catalog();
	store.updateIndexes(items, null);
	return store
		.performRankedLocalSearch(term, items, "ALL", 50)
		.map((item) => item.item_code);
};

describe("Arabic-aware item search", () => {
	it("unifies Arabic letter variants, tashkeel and extra spaces", () => {
		expect(normalizeSearchText("  زاوِيَة   صندوق ")).toBe("زاويه صندوق");
		expect(normalizeSearchText("أإآ ى")).toBe("ااا ي");
		expect(tokenizeSearchText("صندوق بيج")).toEqual(["صندوق", "بيج"]);
	});

	it("returns the exact item code first (S1, S2)", () => {
		expect(search("I-0326")[0]).toBe("I-0326");
		expect(search("164")).toEqual(["164", "I-0164"]);
	});

	it("matches a word anywhere in the name and nothing else (S3, S4)", () => {
		expect(search("طابة").sort()).toEqual(["I-0219", "I-0326"]);
		expect(search("بيج").sort()).toEqual(["I-0324", "I-0325", "I-0326"]);
	});

	it("matches several words in any order (S5)", () => {
		expect(search("صندوق بيج").sort()).toEqual([
			"I-0324",
			"I-0325",
			"I-0326",
		]);
		expect(search("بيج زاوية")).toEqual(["I-0324"]);
	});

	it("treats ة/ه and أ/ا as the same letter (S6)", () => {
		expect(search("زاويه").sort()).toEqual(["I-0151", "I-0324"]);
		expect(search("ابواب")).toEqual(["I-0500"]);
	});

	it("ranks name-starts-with ahead of name-contains", () => {
		expect(search("صندوق").length).toBe(5);
		expect(search("زاوية صندوق")[0]).toBe("I-0324");
	});

	it("finds an item by its barcode", () => {
		expect(search("6281000000017")).toEqual(["I-0500"]);
	});

	it("does not return the whole catalog for punctuation-only input", () => {
		expect(search("( )")).toEqual([]);
	});

	it("filters the selector list with the same normalisation", () => {
		const store = useItemsSearch();
		const items = catalog();
		store.updateIndexes(items, null);
		const { filterAndPaginate } = useItemSearch();
		const visible = filterAndPaginate(items, {
			searchTerm: "طابة صندوق",
			limit: 50,
		}).map((item) => item.item_code);
		expect(visible.sort()).toEqual(["I-0219", "I-0326"]);
	});
});
