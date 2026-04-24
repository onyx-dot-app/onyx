"use client";

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

interface PasteTilePopoverProps {
  text: string;
  rect: DOMRect;
  onDismiss: () => void;
  onTextChange: (newText: string) => void;
}

function PasteTilePopover({
  text,
  rect,
  onDismiss,
  onTextChange,
}: PasteTilePopoverProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  useEffect(() => {
    function handleEscape(e: KeyboardEvent) {
      if (e.key === "Escape") onDismiss();
    }
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [onDismiss]);

  const POPOVER_MAX_H = 340;
  const POPOVER_MAX_W = 400;
  const GAP = 4;
  const fitsBelow = rect.bottom + GAP + POPOVER_MAX_H < window.innerHeight;
  const left = Math.min(rect.left, window.innerWidth - POPOVER_MAX_W - GAP);

  return createPortal(
    <>
      <div className="fixed inset-0 z-40" aria-hidden onClick={onDismiss} />
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
