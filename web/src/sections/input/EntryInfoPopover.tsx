"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Text } from "@opal/components";

interface EntryInfoPopoverProps {
  name: string;
  description: string;
  tileElement: HTMLElement;
  onDismiss: () => void;
}

// Read-only popover anchored to a skill tile, showing its name + description.
// Raw container (anchors to a raw DOM tile node) but renders text via Opal Text.
function EntryInfoPopover({
  name,
  description,
  tileElement,
  onDismiss,
}: EntryInfoPopoverProps) {
  const [rect, setRect] = useState(() => tileElement.getBoundingClientRect());
  const rafId = useRef<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Move focus into the popover on open so screen readers announce it and it's
  // reachable by keyboard, then restore focus (to the input) on dismiss.
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    containerRef.current?.focus();
    return () => previous?.focus?.();
  }, []);

  const updateRect = useCallback(() => {
    if (rafId.current !== null) return;
    rafId.current = requestAnimationFrame(() => {
      rafId.current = null;
      setRect(tileElement.getBoundingClientRect());
    });
  }, [tileElement]);

  useEffect(() => {
    function handleEscape(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onDismiss();
      }
    }
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [onDismiss]);

  useEffect(() => {
    window.addEventListener("resize", updateRect);
    document.addEventListener("scroll", updateRect, true);
    return () => {
      window.removeEventListener("resize", updateRect);
      document.removeEventListener("scroll", updateRect, true);
      if (rafId.current !== null) {
        cancelAnimationFrame(rafId.current);
      }
    };
  }, [updateRect]);

  // Dismiss if the tile is removed from the DOM (Backspace, cut, reset, …),
  // otherwise the popover would anchor to a detached node (rect 0,0).
  useEffect(() => {
    const parent = tileElement.parentNode;
    if (!parent) return;
    const observer = new MutationObserver(() => {
      if (!tileElement.isConnected) onDismiss();
    });
    observer.observe(parent, { childList: true });
    return () => observer.disconnect();
  }, [tileElement, onDismiss]);

  // When opened from an arrow-selected tile, dismiss once it loses the
  // highlight (e.g. the user arrowed away). Click-opened popovers (tile not
  // selected at open) are unaffected.
  useEffect(() => {
    if (!tileElement.classList.contains("rich-input-tile-selected")) return;
    const observer = new MutationObserver(() => {
      if (!tileElement.classList.contains("rich-input-tile-selected")) {
        onDismiss();
      }
    });
    observer.observe(tileElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
    return () => observer.disconnect();
  }, [tileElement, onDismiss]);

  const POPOVER_MAX_H = 240;
  const POPOVER_MAX_W = 320;
  const GAP = 4;
  const fitsBelow = rect.bottom + GAP + POPOVER_MAX_H < window.innerHeight;
  const left = Math.min(rect.left, window.innerWidth - POPOVER_MAX_W - GAP);

  return createPortal(
    <>
      <div
        data-testid="skill-info-backdrop"
        className="fixed inset-0 z-40"
        aria-hidden
        onClick={onDismiss}
      />
      <div
        ref={containerRef}
        role="dialog"
        aria-label={`Skill: ${name}`}
        tabIndex={-1}
        data-testid="skill-info-popover"
        className="fixed z-50 flex flex-col gap-1 bg-background-neutral-00 border border-border-01 rounded-08 shadow-box-02 p-3 overflow-y-auto outline-hidden"
        style={{
          left: Math.max(GAP, left),
          maxWidth: POPOVER_MAX_W,
          maxHeight: POPOVER_MAX_H,
          ...(fitsBelow
            ? { top: rect.bottom + GAP }
            : { bottom: window.innerHeight - rect.top + GAP }),
        }}
      >
        <Text font="main-ui-action" color="text-05">
          {name}
        </Text>
        {description && (
          <Text font="secondary-body" color="text-03">
            {description}
          </Text>
        )}
      </div>
    </>,
    document.body
  );
}

export type { EntryInfoPopoverProps };
export default EntryInfoPopover;
