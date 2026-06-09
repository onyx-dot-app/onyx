import { useEffect, useRef } from "react";

interface UseEscapeInterruptArgs {
  /** Only listen while true (e.g. a response is streaming). */
  enabled: boolean;
  /** Fired on an unhandled Esc. */
  onInterrupt: () => void;
}

const ESCAPE_RESERVED_LAYER_SELECTOR = [
  '[role="dialog"]',
  '[role="alertdialog"]',
  '[role="menu"]',
  '[role="listbox"]',
].join(",");

function isVisibleElement(element: Element): boolean {
  if (!(element instanceof HTMLElement)) return false;
  if (element.hidden || element.getAttribute("aria-hidden") === "true") {
    return false;
  }
  if (element.getClientRects().length === 0) return false;

  const style = window.getComputedStyle(element);
  return style.display !== "none" && style.visibility !== "hidden";
}

function hasVisibleEscapeReservedLayer(): boolean {
  return Array.from(
    document.querySelectorAll(ESCAPE_RESERVED_LAYER_SELECTOR)
  ).some(isVisibleElement);
}

/**
 * Single-Esc interrupt. A window-level listener catches Escape whether or not
 * the input has focus, while still letting dialogs, menus, listboxes, and
 * handlers that already consumed Escape take precedence.
 */
export function useEscapeInterrupt({
  enabled,
  onInterrupt,
}: UseEscapeInterruptArgs): void {
  // Held in a ref so the listener doesn't tear down on onInterrupt identity churn.
  const onInterruptRef = useRef(onInterrupt);
  onInterruptRef.current = onInterrupt;

  useEffect(() => {
    if (!enabled) return;

    const reservedLayerEvents = new WeakSet<KeyboardEvent>();

    function rememberReservedLayer(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (hasVisibleEscapeReservedLayer()) {
        reservedLayerEvents.add(event);
      }
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      // Holding Esc should only interrupt once.
      if (event.repeat) return;
      // A popover/dialog already handled Esc (e.g. closed a menu) — leave it alone.
      if (event.defaultPrevented || event.isComposing) return;
      if (reservedLayerEvents.has(event) || hasVisibleEscapeReservedLayer()) {
        return;
      }

      event.preventDefault();
      onInterruptRef.current();
    }

    window.addEventListener("keydown", rememberReservedLayer, true);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", rememberReservedLayer, true);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [enabled]);
}
