/**
 * Text normalisation shared by every item search path (fast counter hot
 * catalog, browser stored catalog and the item selector display filter).
 *
 * Matching only: stored item names are never changed.
 */

const COMBINING_MARKS = /[̀-ًͯ-ٰٟـ]/g;
const ARABIC_INDIC_DIGITS = /[٠-٩۰-۹]/g;
const NON_WORD_CHARACTERS = /[^\p{L}\p{N}]+/gu;

/**
 * Lowercases, strips accents/tashkeel/tatweel, unifies Arabic letter
 * variants (أ إ آ ٱ → ا, ة → ه, ى → ي) and collapses extra whitespace.
 */
export const normalizeSearchText = (value: unknown): string =>
	(value === null || value === undefined ? "" : String(value))
		.normalize("NFKD")
		.replace(COMBINING_MARKS, "")
		.replace(/ٱ/g, "ا")
		.replace(/ة/g, "ه")
		.replace(/ى/g, "ي")
		.replace(ARABIC_INDIC_DIGITS, (digit) =>
			String(digit.charCodeAt(0) & 0xf),
		)
		.toLowerCase()
		.replace(/\s+/g, " ")
		.trim();

/**
 * Splits text into unique normalised words. Works for any script, so an
 * Arabic query yields real words instead of an empty list.
 */
export const tokenizeSearchText = (value: unknown): string[] => {
	const normalized = normalizeSearchText(value)
		.replace(NON_WORD_CHARACTERS, " ")
		.trim();
	if (!normalized) {
		return [];
	}
	return Array.from(new Set(normalized.split(" ").filter(Boolean)));
};

export const isAsciiSearchToken = (value: string): boolean =>
	/^[a-z0-9]+$/.test(value);
