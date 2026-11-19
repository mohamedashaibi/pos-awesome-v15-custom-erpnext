<template>
	<div class="column-selector-container">
		<v-text-field
			ref="itemSearchField"
			:model-value="itemSearch"
			@update:model-value="onSearchInput"
			@keydown="markUserGesture"
			@paste="markUserGesture"
			@drop="markUserGesture"
			@cut="markUserGesture"
			@compositionstart="markUserGesture"
			@compositionupdate="markUserGesture"
			type="search"
			name="pos-cart-item-search"
			density="compact"
			variant="solo"
			color="primary"
			class="item-search-field pos-themed-input"
			:label="__('Search items or barcode')"
			prepend-inner-icon="mdi-magnify"
				hide-details
				clearable
				autocomplete="off"
				autocorrect="off"
				autocapitalize="off"
				spellcheck="false"
				data-1p-ignore="true"
				data-lpignore="true"
				data-bwignore="true"
				data-form-type="other"
				data-pos-arrow-enters-invoice-grid
			></v-text-field>
		<v-btn
			density="compact"
			variant="text"
			color="primary"
			prepend-icon="mdi-cog-outline"
			@click="toggleColumnSelection"
			class="column-selector-btn"
		>
			{{ __("Columns") }}
		</v-btn>
		<v-dialog v-model="showColumnSelector" max-width="500px" transition="dialog-bottom-transition">
			<v-card class="pos-themed-card">
				<v-card-title class="text-h6 pa-4 d-flex align-center">
					<span>{{ __("Select Columns to Display") }}</span>
					<v-spacer></v-spacer>
					<v-btn
						icon="mdi-close"
						variant="text"
						density="compact"
						:aria-label="__('Close column selector')"
						@click="showColumnSelector = false"
					></v-btn>
				</v-card-title>
				<v-divider></v-divider>
				<v-card-text class="pa-4">
					<v-row dense>
						<v-col
							cols="12"
							v-for="column in availableColumns.filter((col) => !col.required)"
							:key="column.key"
						>
							<v-switch
								:model-value="isTempColumnSelected(column.key)"
								@update:model-value="
									(value) => setTempColumnSelection(column.key, value)
								"
								:label="column.title"
								hide-details
								density="compact"
								color="primary"
								class="column-switch mb-1"
								:disabled="column.required"
							></v-switch>
						</v-col>
					</v-row>
					<div class="text-caption mt-2">
						{{ __("Required columns cannot be hidden") }}
					</div>
				</v-card-text>
				<v-card-actions class="pa-4 pt-0">
					<v-btn color="error" variant="text" @click="cancelColumnSelection">{{
						__("Cancel")
					}}</v-btn>
					<v-spacer></v-spacer>
					<v-btn color="primary" variant="tonal" @click="updateSelectedColumns">{{
						__("Apply")
					}}</v-btn>
				</v-card-actions>
			</v-card>
		</v-dialog>
	</div>
</template>

<script setup>
import { ref } from "vue";

const props = defineProps({
	itemSearch: {
		type: String,
		default: "",
	},
	availableColumns: {
		type: Array,
		default: () => [],
	},
	selectedColumns: {
		type: Array,
		default: () => [],
	},
});

const emit = defineEmits(["update:itemSearch", "update:selectedColumns"]);

const showColumnSelector = ref(false);
const tempSelectedColumns = ref([]);
const itemSearchField = ref(null);

const toggleColumnSelection = () => {
	tempSelectedColumns.value = normalizeColumns(props.selectedColumns);
	showColumnSelector.value = true;
};

const cancelColumnSelection = () => {
	showColumnSelector.value = false;
};

const updateSelectedColumns = () => {
	emit("update:selectedColumns", normalizeColumns(tempSelectedColumns.value));
	showColumnSelector.value = false;
};

// Browsers (Firefox especially) ignore autocomplete="off" and inject the saved
// login username (e.g. "administrator") into this field when a password input
// (the cashier PIN dialog) exists on the page. That silently filters the cart
// to "No matching items". Only accept text that follows a real user gesture
// in this field (keystroke, barcode scan, paste, drop, IME input).
let lastUserGestureAt = 0;
const markUserGesture = () => {
	lastUserGestureAt = Date.now();
};
const USER_GESTURE_WINDOW_MS = 1500;

const getNativeInput = () => itemSearchField.value?.$el?.querySelector?.("input") || null;

const onSearchInput = (value) => {
	const hasText = typeof value === "string" && value.length > 0;
	if (hasText && Date.now() - lastUserGestureAt > USER_GESTURE_WINDOW_MS) {
		const input = getNativeInput();
		if (input) input.value = props.itemSearch || "";
		if (props.itemSearch) emit("update:itemSearch", props.itemSearch);
		return;
	}
	emit("update:itemSearch", value);
};

const focusSearch = () => {
	itemSearchField.value?.focus?.();
};

const normalizeColumns = (columns) =>
	Array.isArray(columns)
		? [...new Set(columns.filter((column) => typeof column === "string"))]
		: [];

const isTempColumnSelected = (key) => tempSelectedColumns.value.includes(key);

const setTempColumnSelection = (key, selected) => {
	const next = new Set(tempSelectedColumns.value);
	if (selected) {
		next.add(key);
	} else {
		next.delete(key);
	}
	tempSelectedColumns.value = [...next];
};

defineExpose({
	focusSearch,
});
</script>

<style scoped>
.item-search-field :deep(input[type="search"]::-webkit-search-cancel-button),
.item-search-field :deep(input[type="search"]::-webkit-search-decoration) {
	-webkit-appearance: none;
	appearance: none;
}
</style>
