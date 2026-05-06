"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

interface PasteTilePopoverProps {
  text: string;
  tileElement: HTMLElement;
  onDismiss: () => void;
  onTextChange: (newText: string) => void;
}

// Popover anchored to a paste tile that lets the user view/edit the full
// pasted text. Rendered via portal so it floats above the contentEditable.
// Uses raw HTML elements because it sits outside the opal/refresh component
// tree (the tile itself is a raw DOM node inside contentEditable).
function PasteTilePopover({
  text,
  tileElement,
  onDismiss,
  onTextChange,
}: PasteTilePopoverProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [rect, setRect] = useState(() => tileElement.getBoundingClientRect());
  const rafId = useRef<number | null>(null);

  const updateRect = useCallback(() => {
    if (rafId.current !== null) return;
    rafId.current = requestAnimationFrame(() => {
      rafId.current = null;
      setRect(tileElement.getBoundingClientRect());
    });
  }, [tileElement]);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

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

  const POPOVER_MAX_H = 340;
  const POPOVER_MAX_W = 400;
  const GAP = 4;
  const fitsBelow = rect.bottom + GAP + POPOVER_MAX_H < window.innerHeight;
  const left = Math.min(rect.left, window.innerWidth - POPOVER_MAX_W - GAP);

  return createPortal(
    <>
      <div
        data-testid="paste-tile-backdrop"
        className="fixed inset-0 z-40"
        aria-hidden
        onClick={onDismiss}
      />
      <div
        role="dialog"
        aria-label="Edit pasted text"
        className="fixed z-50 bg-background-neutral-00 border border-border-01 rounded-08 shadow-02 p-1 max-w-[400px]"
        style={{
          left: Math.max(GAP, left),
          ...(fitsBelow
            ? { top: rect.bottom + GAP }
            : { bottom: window.innerHeight - rect.top + GAP }),
        }}
      >
        <textarea
          ref={textareaRef}
          defaultValue={text}
          onChange={(e) => onTextChange(e.target.value)}
          className="w-full resize-none rounded-04 border-none bg-transparent p-2 font-mono outline-none"
          style={{
            fontSize: "0.8125rem",
            color: "var(--text-04)",
            minHeight: "4rem",
            maxHeight: "16rem",
            fieldSizing: "content",
          }}
        />
      </div>
    </>,
    document.body
  );
}

export type { PasteTilePopoverProps };
export default PasteTilePopover;
