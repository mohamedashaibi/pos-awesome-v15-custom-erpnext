<template>
	<!-- Tanami: customer ledger balance (never shown for the walk-in cash customer) -->
	<div
		v-if="visible"
		class="customer-balance-bar"
		:class="[`customer-balance-bar--${view.tone}`, { 'customer-balance-bar--after': after }]"
		dir="rtl"
		aria-live="polite"
	>
		<template v-if="state.loading">
			<span class="customer-balance-bar__label">{{ __("Loading balance…") }}</span>
		</template>
		<template v-else>
			<span class="customer-balance-bar__label"
				>{{ after ? __("Balance after Invoice") : __("Customer Ledger Balance") }}:</span
			>
			<strong class="customer-balance-bar__figure" dir="ltr">{{ view.figure }}</strong>
			<span class="customer-balance-bar__symbol">{{ view.symbol }}</span>
			<span v-if="view.direction" class="customer-balance-bar__direction">— {{ view.direction }}</span>
		</template>
	</div>
</template>

<script setup>
import { computed, watch } from "vue";
import {
	customerLedgerBalance as state,
	describeLedgerBalance,
	refreshCustomerLedgerBalance,
} from "../../../composables/pos/customer/useCustomerLedgerBalance";

const props = defineProps({
	// the customer whose balance is shown; the bar keeps the shared figure in step with it
	customer: { type: String, default: "" },
	company: { type: String, default: "" },
	currency: { type: String, default: "" },
	// payment dialog: balance once this invoice is submitted (`change` is added to the balance)
	after: { type: Boolean, default: false },
	change: { type: Number, default: 0 },
});

const __ = window.__ || ((text) => text);

watch(
	() => [props.customer, props.company],
	([customer, company]) => {
		if ((customer || "") !== state.customer || (customer && !state.available && !state.loading)) {
			refreshCustomerLedgerBalance(customer, company);
		}
	},
	{ immediate: true },
);

const visible = computed(
	() => Boolean(props.customer) && (state.loading || (state.available && !state.isCashCustomer)),
);
const view = computed(() =>
	describeLedgerBalance(state.balance + (props.after ? props.change : 0), props.currency),
);
</script>

<style scoped>
.customer-balance-bar {
	display: flex;
	align-items: baseline;
	gap: 6px;
	margin-top: 4px;
	padding: 4px 12px;
	border-radius: 8px;
	font-size: 1.05rem;
	line-height: 1.5;
	border: 1px solid transparent;
	color: #5f6b68;
	background: rgba(120, 130, 127, 0.1);
}
.customer-balance-bar__figure {
	font-weight: 700;
	font-size: 1.15rem;
}
.customer-balance-bar--debit {
	color: #b3261e;
	background: rgba(179, 38, 30, 0.08);
	border-color: rgba(179, 38, 30, 0.25);
}
.customer-balance-bar--credit {
	color: #1b7f4d;
	background: rgba(27, 127, 77, 0.08);
	border-color: rgba(27, 127, 77, 0.25);
}
.customer-balance-bar--after {
	margin-top: 8px;
}
</style>
