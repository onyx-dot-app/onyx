import { forwardRef, useCallback } from "react";
import {
  FlashList,
  type FlashListProps,
  type FlashListRef,
  type ListRenderItem,
} from "@shopify/flash-list";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Minimal, opinionated prop surface re-exported from FlashList. We expose the
 * props the chat thread actually needs and keep them generically typed over the
 * row data type `<T>`. Anything else on FlashList can still be passed through
 * via `...rest` (the surface intentionally extends `FlashListProps<T>`).
 */
export interface VirtualListProps<T>
  extends Omit<FlashListProps<T>, "data" | "renderItem" | "keyExtractor"> {
  /** The backing data — a plain, immutable array of row items. */
  data: ReadonlyArray<T> | null | undefined;

  /**
   * Renders a single row. MUST point at a stable, memoized component (see the
   * performance rules in this file's doc comment). Prefer defining `renderItem`
   * outside render, or wrapping it in `useCallback`, so its identity is stable.
   */
  renderItem: ListRenderItem<T> | null | undefined;

  /**
   * Returns a STABLE, unique key for each item. Stable keys are what let
   * FlashList recycle cells correctly across data changes (insertions,
   * streaming appends, re-orders). Defaults to `index` only as a last resort —
   * always provide a real id when one exists.
   */
  keyExtractor?: (item: T, index: number) => string;
}

// ---------------------------------------------------------------------------
// VirtualList
// ---------------------------------------------------------------------------

/**
 * Thin, typed generic wrapper over `@shopify/flash-list` (v2) that bakes in the
 * project's virtualization + NativeWind performance discipline. This is the
 * reusable LIST primitive the chat thread (doc 06) builds on.
 *
 * ## Performance rules (READ BEFORE WRITING A ROW)
 *
 * NativeWind re-renders every dependent when the theme / colorScheme changes,
 * and FlashList recycles cells aggressively. To keep scrolling smooth:
 *
 * 1. **Wrap row components in `React.memo`.** A row must not re-render unless
 *    its own props change. `MessageRow` in this folder is the canonical
 *    example. An un-memoized row defeats recycling.
 *
 * 2. **Keep every per-row `className` STATIC — never a template literal.**
 *    NativeWind compiles classes by scanning source for static strings, so
 *    `` `bg-${tone}` `` silently produces no style AND forces a recompute.
 *    Pick between a small set of pre-written static class strings (e.g. via a
 *    `role === "user" ? CLASS_A : CLASS_B` switch, or CVA static variants).
 *    Dynamic colors go through `style` + `useThemeColors`, not className.
 *
 * 3. **Provide a stable `keyExtractor`.** Use a real item id when available.
 *    Stable keys are required for correct cell recycling and for layout
 *    animations during streaming appends.
 *
 * FlashList v2 auto-measures item sizes, so there is intentionally NO
 * `estimatedItemSize` prop — passing one is a no-op in v2 and is omitted here.
 */
function VirtualListInner<T>(
  {
    data,
    renderItem,
    keyExtractor,
    // Perf-friendly defaults. All overridable via props.
    showsVerticalScrollIndicator = false,
    keyboardShouldPersistTaps = "handled",
    onEndReachedThreshold = 0.5,
    ...rest
  }: VirtualListProps<T>,
  ref: React.Ref<FlashListRef<T>>,
) {
  // Default key extractor: prefer index-stable fallback. Callers SHOULD pass a
  // real id-based extractor; this only guarantees a key always exists.
  const resolvedKeyExtractor = useCallback(
    (item: T, index: number) =>
      keyExtractor ? keyExtractor(item, index) : String(index),
    [keyExtractor],
  );

  return (
    <FlashList<T>
      ref={ref}
      data={data}
      renderItem={renderItem}
      keyExtractor={resolvedKeyExtractor}
      showsVerticalScrollIndicator={showsVerticalScrollIndicator}
      keyboardShouldPersistTaps={keyboardShouldPersistTaps}
      onEndReachedThreshold={onEndReachedThreshold}
      {...rest}
    />
  );
}

/**
 * Generic `forwardRef` wrapper. `forwardRef` erases the generic, so we cast the
 * result back to a generic-preserving call signature. This lets callers write
 * `<VirtualList<Message> ... />` and still forward a typed `FlashListRef`.
 */
const VirtualList = forwardRef(VirtualListInner) as <T>(
  props: VirtualListProps<T> & { ref?: React.Ref<FlashListRef<T>> },
) => React.ReactElement | null;

export { VirtualList };
export type { ListRenderItem, ListRenderItemInfo, FlashListRef } from "@shopify/flash-list";
