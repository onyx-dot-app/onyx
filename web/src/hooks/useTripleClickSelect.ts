"use client";

import { useCallback } from "react";

/**
 * Hook that implements standard triple-click text selection behavior:
 * - Single click: place cursor (browser default)
 * - Double click: select word (browser default)
 * - Triple click: select entire content of the target element
 *
 * Uses onMouseDown with event.detail to detect click count and preventDefault
 * on triple-click to avoid the native line selection flashing before our selection.
 *
 * @param elementRef - Ref to the element whose content should be selected on triple-click
 * @returns onMouseDown handler to attach to the element
 */
export function useTripleClickSelect(
  elementRef: React.RefObject<HTMLElement | null>
) {
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      // event.detail gives the click count (1, 2, 3, etc.)
      if (e.detail === 3) {
        // Prevent native triple-click (line/paragraph selection)
        e.preventDefault();

        const element = elementRef.current;
        if (!element) return;

        const selection = window.getSelection();
        if (!selection) return;

        const range = document.createRange();
        range.selectNodeContents(element);
        selection.removeAllRanges();
        selection.addRange(range);
      }
    },
    [elementRef]
  );

  return handleMouseDown;
}
