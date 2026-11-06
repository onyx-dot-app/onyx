import { useSyncExternalStore, type ComponentProps } from "react";
import type { Popover } from "@opal/components";

/** Where a card's pill popover opens: beside the card, or below it with its end at the card's end. */
export type PopoverPlacement = "beside" | "below";

/** The floating panels a message card opens. */
export type FloatingPanel = "failedDocs" | "stackTrace";

export const PLACEMENT_PROPS = {
  beside: { side: "left", align: "start" },
  below: { side: "bottom", align: "end" },
} as const satisfies Record<
  PopoverPlacement,
  Pick<ComponentProps<typeof Popover.Content>, "side" | "align">
>;

// Under this content width the 480 px trace beside the side panel would cover nearly all of the column, so it opens under its card.
const BESIDE_MIN_CONTENT_WIDTH = 1024;

/** The failed documents list hangs under its card at every width: 640 wide beside the panel it would cover the whole column. */
export function popoverPlacementFor(
  panel: FloatingPanel,
  contentWidth: number
): PopoverPlacement {
  if (panel === "failedDocs") return "below";
  return contentWidth >= BESIDE_MIN_CONTENT_WIDTH ? "beside" : "below";
}

// The content area beside the admin sidebar, which folds without a window resize.
const MAIN_CONTAINER = "[data-main-container]";

// One observer for every card on the page, so a resize re-renders only the cards whose placement flips.
const listeners = new Set<() => void>();
let observer: ResizeObserver | null = null;
let contentWidth: number | null = null;

function measureContentWidth(): number {
  const main = document.querySelector<HTMLElement>(MAIN_CONTAINER);
  return main?.getBoundingClientRect().width ?? window.innerWidth;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (observer === null) {
    const update = () => {
      contentWidth = measureContentWidth();
      listeners.forEach((notify) => notify());
    };
    observer = new ResizeObserver(update);
    observer.observe(
      document.querySelector(MAIN_CONTAINER) ?? document.documentElement
    );
    update();
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size > 0) return;
    observer?.disconnect();
    observer = null;
    contentWidth = null;
  };
}

/** The panel's placement for the current content width. Before the first measure (and on the server) it assumes a wide page. */
export function usePopoverPlacement(panel: FloatingPanel): PopoverPlacement {
  const wide = popoverPlacementFor(panel, Number.POSITIVE_INFINITY);
  return useSyncExternalStore(
    subscribe,
    () =>
      contentWidth === null ? wide : popoverPlacementFor(panel, contentWidth),
    () => wide
  );
}
