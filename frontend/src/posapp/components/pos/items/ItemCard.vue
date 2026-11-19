<template>
	<div
		:class="['card-item-card', { 'item-highlighted': isItemHighlighted }]"
		data-pos-keyboard-target="item-card"
		:data-testid="`pos-item-card-${item.item_code}`"
		:data-item-code="item.item_code"
		tabindex="0"
		role="button"
		:aria-label="`${item.item_name || item.item_code}`"
		@click="onClick"
		@keydown="onKeyboardSelect"
		:draggable="true"
		@dragstart="onDragStart"
		@dragend="onDragEnd"
	>
		<div :class="['card-item-image-container', { 'is-monogram': !item.image }]">
			<v-img
				v-if="item.image"
				:src="item.image"
				class="card-item-image"
				cover
				:alt="item.item_name"
			>
				<template #placeholder>
					<div class="image-placeholder">
						<v-icon size="28" color="grey-lighten-2"> mdi-image </v-icon>
					</div>
				</template>
			</v-img>
			<!-- No photo: a tinted monogram reads better than a stock placeholder -->
			<div v-else :class="['card-item-monogram', `tone-${monogramTone}`]" aria-hidden="true">
				{{ monogram }}
			</div>
		</div>
		<div class="card-item-content">
			<div class="card-item-header">
				<h4 class="card-item-name">{{ item.item_name }}</h4>
				<span class="card-item-code">{{ item.item_code }}</span>
			</div>
			<div class="card-item-details">
				<div class="card-item-price">
					<div class="primary-price">
						<span class="currency-symbol">
							{{ currencySymbol(primaryCurrency) }}
						</span>
						<span class="price-amount">
							{{ formatCurrency(primaryRate, primaryCurrency, primaryPrecision) }}
						</span>
						<ItemRateInfoMenu
							v-if="showRateInfo"
							:rate-info="rateInfo"
							:currency-symbol="currencySymbol"
							:format-currency="formatCurrency"
							:rate-precision="ratePrecision"
						/>
					</div>
					<div v-if="showSecondaryPrice" class="secondary-price">
						<span class="currency-symbol">
							{{ currencySymbol(secondaryCurrency) }}
						</span>
						<span class="price-amount">
							{{ formatCurrency(secondaryRate, secondaryCurrency, secondaryPrecision) }}
						</span>
					</div>
				</div>
				<div class="card-item-stock">
					<v-icon size="small" class="stock-icon"> mdi-package-variant </v-icon>
					<span
						class="stock-amount"
						:class="{
							'negative-number': isNegative(item.actual_qty),
						}"
					>
						{{ formattedActualQty }}
					</span>
					<span class="stock-uom">{{ item.stock_uom || "" }}</span>
				</div>
			</div>
		</div>
	</div>
</template>

<script setup>
import { computed } from "vue";
import ItemRateInfoMenu from "./ItemRateInfoMenu.vue";
import { priceListToSelectedCurrency } from "../../../utils/erpnextCurrency";

const props = defineProps({
	item: { type: Object, required: true },
	posProfile: { type: Object, required: true },
	context: { type: String, default: "pos" },
	selectedCurrency: { type: String, default: "" },
	selectedExchangeRate: { type: Number, default: 1 },
	selectedConversionRate: { type: Number, default: 1 },
	hideQtyDecimals: { type: Boolean, default: false },
	showRateInfo: { type: Boolean, default: true },
	getItemRateInfo: { type: Function, required: true },
	isItemHighlighted: { type: Boolean, default: false },
	currencySymbol: { type: Function, required: true },
	formatCurrency: { type: Function, required: true },
	formatNumber: { type: Function, required: true },
	ratePrecision: { type: Function, required: true },
	isNegative: { type: Function, default: (val) => val < 0 },
});

const emit = defineEmits(["click", "dragstart", "dragend"]);

const primaryCurrency = computed(() => {
	if (props.context === "purchase") {
		return (
			props.item.original_currency ||
			props.item.currency ||
			props.item.price_list_currency ||
			props.posProfile.currency
		);
	}
	return (
		props.item.original_currency ||
		props.item.currency ||
		props.item.price_list_currency ||
		props.posProfile.currency
	);
});

const primaryRate = computed(() => {
	if (props.context === "purchase") {
		return props.item.original_rate ?? props.item.rate ?? props.item.standard_rate ?? 0;
	}
	return props.item.original_rate ?? props.item.rate ?? 0;
});

const primaryPrecision = computed(() => {
	return props.ratePrecision(primaryRate.value);
});

const secondaryRate = computed(() => {
	return priceListToSelectedCurrency(
		{
			pos_profile: props.posProfile,
			price_list_currency: primaryCurrency.value,
			selected_currency: props.selectedCurrency || props.posProfile.currency,
			exchange_rate: props.selectedExchangeRate,
			conversion_rate: props.selectedConversionRate,
		},
		primaryRate.value,
	);
});

const secondaryPrecision = computed(() => {
	return props.ratePrecision(secondaryRate.value);
});

// First letter of the item name, and a stable tint picked from the item code
const monogram = computed(() => {
	const name = String(props.item.item_name || props.item.item_code || "").trim();
	return Array.from(name)[0] || "?";
});
const monogramTone = computed(() => {
	const code = String(props.item.item_code || "");
	let hash = 0;
	for (let i = 0; i < code.length; i++) hash = (hash * 31 + code.charCodeAt(i)) >>> 0;
	return hash % 6;
});

const rateInfo = computed(() => props.getItemRateInfo(props.item));

const secondaryCurrency = computed(() => props.selectedCurrency);

const showSecondaryPrice = computed(() => {
	return (
		props.context !== "purchase" &&
		props.posProfile.posa_allow_multi_currency &&
		Boolean(props.selectedCurrency) &&
		props.selectedCurrency !== primaryCurrency.value
	);
});

const formattedActualQty = computed(() => {
	const numericQty = Number(props.item.actual_qty ?? 0);
	if (!Number.isFinite(numericQty)) {
		return 0;
	}
	if (props.hideQtyDecimals) {
		return props.formatNumber(Math.round(numericQty), 0);
	}
	return props.formatNumber(numericQty, 4);
});

const onClick = (event) => {
	emit("click", event, props.item);
};

const onKeyboardSelect = (event) => {
	const key = event?.key || "";
	if (key !== "Enter" && key !== " ") {
		return;
	}
	event.preventDefault?.();
	emit("click", event, props.item);
};

const onDragStart = (event) => {
	emit("dragstart", event, props.item);
};

const onDragEnd = (event) => {
	emit("dragend", event);
};
</script>

<style scoped>
.card-item-card {
	position: relative;
	display: flex;
	flex-direction: column;
	width: 100%;
	height: 100%;
	overflow: hidden;
	cursor: pointer;
	background: var(--pos-surface-raised);
	border: 1px solid var(--pos-border-light);
	border-radius: var(--pos-radius-md);
	box-shadow: var(--pos-elevation-1);
	transition:
		transform 0.18s cubic-bezier(0.4, 0, 0.2, 1),
		box-shadow 0.18s ease,
		border-color 0.18s ease,
		background-color 0.18s ease;
	-webkit-tap-highlight-color: transparent;
	user-select: none;
}

.card-item-card:hover {
	transform: translateY(-2px);
	border-color: color-mix(in srgb, var(--pos-primary) 45%, var(--pos-border));
	box-shadow: var(--pos-elevation-2);
}

.card-item-card:active {
	transform: scale(0.98);
	box-shadow: var(--pos-elevation-1);
}

.card-item-card:focus-visible {
	outline: none;
	border-color: var(--pos-primary);
	box-shadow: 0 0 0 3px var(--pos-focus-halo);
}

.card-item-card.item-highlighted {
	border-color: var(--pos-primary);
	background: var(--pos-primary-container);
	box-shadow: 0 0 0 3px var(--pos-focus-halo), var(--pos-elevation-2);
}

/* Photo / monogram tile */
.card-item-image-container {
	position: relative;
	flex-shrink: 0;
	height: 84px;
	margin: 8px 8px 0;
	overflow: hidden;
	border-radius: calc(var(--pos-radius-md) - 4px);
	background: var(--pos-surface-muted);
}

.card-item-image {
	width: 100%;
	height: 100%;
}

.image-placeholder {
	display: flex;
	align-items: center;
	justify-content: center;
	width: 100%;
	height: 100%;
}

.card-item-monogram {
	display: flex;
	align-items: center;
	justify-content: center;
	width: 100%;
	height: 100%;
	/* Nudged down so the stock badge in the corner never touches the letter */
	padding-top: 14px;
	font-size: 2rem;
	font-weight: 700;
	line-height: 1;
	--tone: var(--pos-primary);
	color: var(--tone);
	background:
		radial-gradient(120% 90% at 85% 0%, color-mix(in srgb, var(--tone) 22%, transparent), transparent 70%),
		color-mix(in srgb, var(--tone) 12%, var(--pos-surface));
}

/* Six calm tints derived from the theme, so dark mode follows automatically */
.card-item-monogram.tone-1 { --tone: var(--pos-accent); }
.card-item-monogram.tone-2 { --tone: color-mix(in srgb, var(--pos-primary) 60%, #2b6cb0); }
.card-item-monogram.tone-3 { --tone: color-mix(in srgb, var(--pos-accent) 55%, #b54a2c); }
.card-item-monogram.tone-4 { --tone: color-mix(in srgb, var(--pos-primary) 55%, #6b4fa0); }
.card-item-monogram.tone-5 { --tone: color-mix(in srgb, var(--pos-text-secondary) 80%, var(--pos-primary)); }

/* Text */
.card-item-content {
	display: flex;
	flex-direction: column;
	flex-grow: 1;
	gap: 6px;
	min-height: 0;
	padding: 10px 12px 12px;
}

.card-item-header {
	display: flex;
	flex-direction: column;
	gap: 2px;
	min-width: 0;
}

.card-item-name {
	margin: 0;
	font-size: 0.92rem;
	font-weight: 600;
	line-height: 1.35;
	color: var(--pos-text-primary);
	overflow: hidden;
	display: -webkit-box;
	-webkit-line-clamp: 2;
	line-clamp: 2;
	-webkit-box-orient: vertical;
}

.card-item-code {
	display: block;
	overflow: hidden;
	font-size: 0.68rem;
	letter-spacing: 0.04em;
	color: var(--pos-text-muted);
	white-space: nowrap;
	text-overflow: ellipsis;
}

/* Price + stock on one line */
.card-item-details {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 6px;
	margin-top: auto;
	min-width: 0;
}

.card-item-price {
	display: flex;
	flex: 1;
	flex-direction: column;
	min-width: 0;
}

.primary-price {
	display: flex;
	align-items: baseline;
	gap: 4px;
	white-space: nowrap;
	font-size: 1.1rem;
	font-weight: 700;
	font-variant-numeric: tabular-nums;
	color: var(--pos-primary);
}

.primary-price .currency-symbol {
	font-size: 0.72rem;
	font-weight: 600;
	opacity: 0.8;
}

.primary-price > .v-btn {
	align-self: center;
}

.secondary-price {
	font-size: 0.74rem;
	white-space: nowrap;
	color: var(--pos-text-secondary);
}

/* Stock sits on the photo tile as a badge, so the price row never gets crowded */
.card-item-stock {
	position: absolute;
	top: 14px;
	inset-inline-end: 14px;
	display: inline-flex;
	align-items: center;
	gap: 3px;
	padding: 2px 8px;
	font-size: 0.72rem;
	line-height: 1.5;
	white-space: nowrap;
	color: var(--pos-text-secondary);
	background: color-mix(in srgb, var(--pos-surface-raised) 88%, transparent);
	border: 1px solid var(--pos-border-light);
	border-radius: 999px;
	backdrop-filter: blur(4px);
}

.stock-icon {
	font-size: 0.85rem !important;
	opacity: 0.7;
}

.stock-amount {
	font-weight: 600;
	font-variant-numeric: tabular-nums;
}

.stock-amount.negative-number {
	color: rgb(var(--v-theme-error));
}

.stock-uom {
	font-size: 0.66rem;
	text-transform: uppercase;
	opacity: 0.8;
}

@media (max-width: 768px) {
	.card-item-image-container {
		height: 72px;
	}

	.card-item-content {
		padding: 8px 10px 10px;
	}

	.card-item-name {
		font-size: 0.86rem;
	}
}

@media (prefers-reduced-motion: reduce) {
	.card-item-card,
	.card-item-card:hover,
	.card-item-card:active {
		transition: none;
		transform: none;
	}
}
</style>
