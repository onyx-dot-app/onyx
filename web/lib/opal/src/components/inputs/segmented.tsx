"use client";

import React from "react";
import { Text } from "@opal/components";

/**
 * Shared behavior for segmented numeric fields (InputTime, InputDatePicker),
 * the TS counterpart of shared.css's segmented-field chrome. Each component
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
      const digits = e.target.value.replace(/\D/g, "").slice(0, maxLen);
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

      // Arrows only cross a segment edge with a collapsed caret, so
      // Shift+Arrow selection and mid-segment caret moves stay native.
      const { selectionStart, selectionEnd, value } = e.currentTarget;
      if (e.shiftKey || selectionStart !== selectionEnd) return;
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
