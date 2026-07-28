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

/**
 * Per-render factory for segment onKeyDown: Enter commits the draft, and
 * Backspace in an already-empty segment hops focus back.
 */
export function makeSegmentKeyDownHandler<S extends { [K in keyof S]: string }>(
  segments: S,
  commit: (next: S) => void
) {
  return (
    part: keyof S,
    prevRef: React.RefObject<HTMLInputElement | null> | null
  ) =>
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        commit(segments);
        return;
      }
      if (e.key === "Backspace" && segments[part] === "") {
        prevRef?.current?.focus();
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
