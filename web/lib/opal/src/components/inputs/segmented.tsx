"use client";

import React from "react";
import { Text } from "@opal/components";

/**
 * Shared behavior for segmented numeric fields (InputTime, InputDatePicker,
 * InputCurrency), the TS counterpart of shared.css's segmented-field chrome. Each component
 * keeps its own domain model (segment shape, parse/format, commit rules);
 * this module owns how a segment input behaves.
 */

/** Static props every chromeless numeric segment input shares. */
export const SEGMENT_INPUT_PROPS = {
  className: "opal-input-segment",
  type: "text",
  inputMode: "numeric",
  autoComplete: "off",
} as const;

/**
 * Arabic-Indic (U+0660) and Extended Arabic-Indic (U+06F0) digits, which the
 * Arabic locale types, read as their ASCII digits.
 */
export function toAsciiDigits(text: string): string {
  return text.replace(/[\u0660-\u0669\u06F0-\u06F9]/g, (digit) =>
    String((digit.charCodeAt(0) - 0x0660) % 0x90)
  );
}

/**
 * Pasted text with ASCII digits and without whitespace or the invisible
 * direction marks some locales put around numbers (Arabic's "\u200F١٢٫٥٠ US$").
 */
export function cleanPastedText(text: string): string {
  return toAsciiDigits(text).replace(
    /[\s\u061C\u200E\u200F\u202A-\u202E\u2066-\u2069]/g,
    ""
  );
}

/**
 * Returns a ref for a caret position to restore once the next render lands.
 * Applied in a layout effect keyed on `segments`, synchronously after React
 * writes the value and before any later input event, so it can never
 * overwrite a newer caret move.
 */
export function usePendingCaret(segments: unknown) {
  const pendingCaretRef = React.useRef<{
    input: HTMLInputElement;
    position: number;
  } | null>(null);
  React.useLayoutEffect(() => {
    const pending = pendingCaretRef.current;
    if (!pending) return;
    pendingCaretRef.current = null;
    pending.input.setSelectionRange(pending.position, pending.position);
  }, [segments]);
  return pendingCaretRef;
}

/**
 * Per-render factory for segment onChange: digits only, capped at maxLen,
 * advancing focus to the next segment when full.
 */
export function makeSegmentChangeHandler<S extends { [K in keyof S]: string }>(
  setSegments: React.Dispatch<React.SetStateAction<S>>
) {
  return (
    part: keyof S,
    maxLen: number,
    nextRef: React.RefObject<HTMLInputElement | null> | null
  ) =>
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const digits = toAsciiDigits(e.target.value)
        .replace(/\D/g, "")
        .slice(0, maxLen);
      setSegments((prev) => ({ ...prev, [part]: digits }));
      if (digits.length === maxLen) nextRef?.current?.focus();
    };
}

/** Focuses a segment with the caret at its start or end. */
function focusSegment(
  ref: React.RefObject<HTMLInputElement | null> | null,
  caret: "start" | "end"
): boolean {
  const input = ref?.current;
  if (!input) return false;
  input.focus();
  const position = caret === "start" ? 0 : input.value.length;
  input.setSelectionRange(position, position);
  return true;
}

/**
 * Per-render factory for segment onKeyDown: Enter commits the draft,
 * Backspace in an already-empty segment hops focus back, and ArrowLeft /
 * ArrowRight at a segment's edge move to the adjacent segment.
 */
export function makeSegmentKeyDownHandler<S extends { [K in keyof S]: string }>(
  segments: S,
  commit: (next: S) => void
) {
  return (
    part: keyof S,
    prevRef: React.RefObject<HTMLInputElement | null> | null,
    nextRef: React.RefObject<HTMLInputElement | null> | null = null
  ) =>
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        // Commit the draft, and stop the keystroke there: inside a <form>,
        // an unhandled Enter on an input is a native form submission.
        e.preventDefault();
        commit(segments);
        return;
      }
      if (e.key === "Backspace" && segments[part] === "") {
        prevRef?.current?.focus();
        e.preventDefault();
        return;
      }

      // Only a plain arrow with a collapsed caret crosses a segment edge.
      // Modified arrows (selection, word jumps, Alt+Arrow history) and
      // mid-segment caret moves stay native.
      const { selectionStart, selectionEnd, value } = e.currentTarget;
      if (
        e.shiftKey ||
        e.ctrlKey ||
        e.metaKey ||
        e.altKey ||
        selectionStart !== selectionEnd
      ) {
        return;
      }
      if (
        e.key === "ArrowLeft" &&
        selectionStart === 0 &&
        focusSegment(prevRef, "end")
      ) {
        e.preventDefault();
      } else if (
        e.key === "ArrowRight" &&
        selectionEnd === value.length &&
        focusSegment(nextRef, "start")
      ) {
        e.preventDefault();
      }
    };
}

/** Separator glyph rendered between segments. */
export function SegmentSeparator({ children }: { children: string }) {
  return (
    <Text font="main-ui-mono" color="text-02" aria-hidden>
      {children}
    </Text>
  );
}
