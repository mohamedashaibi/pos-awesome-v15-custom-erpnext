import { ref, computed, onMounted, onUnmounted, nextTick, watch } from "vue";
import _ from "lodash";
import {
	getCardColumns,
	getCardGap,
	getCardPadding,
} from "../../../utils/itemSelectorLayout.js";

type SelectorLayoutOptions = {
	resizeDebounce?: number;
	loadVisibleItems?: () => void;
};

/**
 * Manages the layout metrics and resize behavior for the ItemsSelector component.
 * Handles calculation of grid columns, card dimensions, and overflow detection.
 */
export function useItemSelectorLayout(options: SelectorLayoutOptions = {}) {
	const {
		resizeDebounce = 100,
		loadVisibleItems, // Method to load more items on scroll (pagination)
	} = options;

	// State
	const windowWidth = ref(window.innerWidth);
	const isOverflowing = ref(false);
	const itemsContainerRef = ref<any>(null);
	const scrollThrottle = ref<number | null>(null);

	// Width of the items panel itself, kept current by a ResizeObserver
	const containerWidth = ref(0);
	const MIN_CARD_WIDTH = 150;
	const MAX_COLUMNS = 6;
	const MIN_USABLE_HEIGHT = 160;

	// Computed Metrics
	const cardGap = computed(() => getCardGap(windowWidth.value));
	const cardPadding = computed(() => getCardPadding(windowWidth.value));
	// Columns follow the panel width, not the window, so cards never overflow the panel
	const cardColumns = computed(() => {
		const width = containerWidth.value;
		if (!width) {
			return getCardColumns(windowWidth.value);
		}
		const usable = width - cardPadding.value * 2 + cardGap.value;
		const fit = Math.floor(usable / (MIN_CARD_WIDTH + cardGap.value));
		return Math.min(MAX_COLUMNS, Math.max(1, fit));
	});

	const cardRowHeight = computed(() => (windowWidth.value <= 768 ? 196 : 212));

	const cardSlotHeight = computed(() => cardRowHeight.value + cardGap.value);
	const cardSlotWidth = computed(() => cardColumnWidth.value + cardGap.value);

	const cardContainerWidth = computed(() => containerWidth.value || windowWidth.value * 0.4);

	const cardColumnWidth = computed(() => {
		const columns = Math.max(1, cardColumns.value);
		// Note: We might need a more robust way to get container width if it's dynamic
		// Ideally pass a ref to the container element
		const containerWidth = cardContainerWidth.value || 0;
		if (!containerWidth) {
			return 240; // Safe default
		}

		const gapTotal = cardGap.value * (columns - 1);
		const paddingTotal = cardPadding.value * 2;
		const available = Math.max(0, containerWidth - gapTotal - paddingTotal);
		return Math.max(MIN_CARD_WIDTH, Math.floor(available / columns));
	});

	// Actions
	const updateWindowWidth = () => {
		windowWidth.value = window.innerWidth;
	};

	const scheduleCardMetricsUpdate = _.debounce(() => {
		updateWindowWidth();
		// Force re-evaluation of container width if needed by accessing ref
		if (itemsContainerRef.value) {
			// Trigger reactivity if needed, though windowWidth usually drives computed props
		}
		checkItemContainerOverflow();
	}, resizeDebounce);

	const getItemsContainerElement = (): HTMLElement | null => {
		if (!itemsContainerRef.value) return null;
		// Handle both Vue component ref and raw element
		return (itemsContainerRef.value.$el ||
			itemsContainerRef.value) as HTMLElement | null;
	};

	const checkItemContainerOverflow = () => {
		const el = getItemsContainerElement();
		if (!el) {
			isOverflowing.value = false;
			return;
		}

		const containerHeight = parseFloat(
			getComputedStyle(el).getPropertyValue("--container-height"),
		);
		if (isNaN(containerHeight)) {
			isOverflowing.value = false;
			return;
		}

		const stickyHeader = el
			.closest(".dynamic-padding")
			?.querySelector(".sticky-header") as HTMLElement | null;
		const headerHeight = stickyHeader ? stickyHeader.offsetHeight : 0;
		const availableHeight = containerHeight - headerHeight;

		// Only apply if calculated height is valid. On phones the measured height is
		// circular (it shrinks to whatever cap we set), so a tiny value must not stick.
		if (availableHeight > MIN_USABLE_HEIGHT) {
			el.style.maxHeight = `${availableHeight}px`;
			isOverflowing.value = el.scrollHeight > availableHeight;
		} else {
			el.style.maxHeight = "";
			isOverflowing.value = el.scrollHeight > el.clientHeight;
		}

		// Also schedule metrics update as this might affect layout
		// But be careful of infinite loops; separate updateWindowWidth logic if needed
	};

	const onListScroll = (event: Event) => {
		if (scrollThrottle.value) return;

		scrollThrottle.value = requestAnimationFrame(() => {
			try {
				const el = event.target as HTMLElement | null;
				if (!el) return;
				if (el.scrollTop + el.clientHeight >= el.scrollHeight - 50) {
					// Trigger pagination via callback
					if (typeof loadVisibleItems === "function") {
						// We need access to currentPage logic, but usually loadVisibleItems handles the "next/more" logic
						loadVisibleItems();
					}
				}
			} catch (error: unknown) {
				console.error("Error in list scroll handler:", error);
			} finally {
				scrollThrottle.value = null;
			}
		});
	};

	let containerObserver: ResizeObserver | null = null;
	const observeContainer = () => {
		containerObserver?.disconnect();
		const el = getItemsContainerElement();
		if (!el || typeof ResizeObserver === "undefined") return;
		containerObserver = new ResizeObserver((entries) => {
			const entry = entries[0];
			if (entry) containerWidth.value = Math.floor(entry.contentRect.width);
		});
		containerObserver.observe(el);
		containerWidth.value = el.clientWidth;
	};
	watch(itemsContainerRef, () => nextTick(observeContainer));

	// Lifecycle
	onMounted(() => {
		window.addEventListener("resize", scheduleCardMetricsUpdate);
		nextTick(() => {
			updateWindowWidth();
			checkItemContainerOverflow();
			observeContainer();
		});
	});

	onUnmounted(() => {
		window.removeEventListener("resize", scheduleCardMetricsUpdate);
		containerObserver?.disconnect();
		if (scrollThrottle.value) {
			cancelAnimationFrame(scrollThrottle.value);
		}
		scheduleCardMetricsUpdate.cancel();
	});

	return {
		// Refs
		windowWidth,
		isOverflowing,
		itemsContainerRef, // Bind this to the container in template

		// Computed
		cardColumns,
		cardGap,
		cardPadding,
		cardRowHeight,
		cardSlotHeight,
		cardSlotWidth,
		cardColumnWidth,

		// Methods
		checkItemContainerOverflow,
		scheduleCardMetricsUpdate,
		onListScroll,
	};
}
