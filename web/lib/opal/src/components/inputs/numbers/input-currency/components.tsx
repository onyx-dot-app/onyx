"use client";

import "@opal/components/inputs/shared.css";
import React from "react";
import type { InputVariants } from "@opal/types";
import {
  SEGMENT_INPUT_PROPS,
  SegmentSeparator,
  makeSegmentChangeHandler,
  makeSegmentKeyDownHandler,
} from "@opal/components/inputs/segmented";
import { useOpalStrings } from "@opal/strings";

// ---------------------------------------------------------------------------
// Types and segment helpers
// ---------------------------------------------------------------------------

interface AmountSegments {
  whole: string;
  fraction: string;
}

const EMPTY_SEGMENTS: AmountSegments = { whole: "", fraction: "" };

// Characters that end the whole-number segment, besides the locale separator.
const DECIMAL_KEYS = [".", ","];

// Negative, non-finite and exponent-sized values render empty.
function toSegments(
  value: number | null,
  decimalPlaces: number,
  minFractionDigits: number
): AmountSegments {
  if (value == null || !Number.isFinite(value) || value < 0 || value >= 1e21) {
    return EMPTY_SEGMENTS;
  }
  const [whole = "", fraction = ""] = value.toFixed(decimalPlaces).split(".");
  // Trim trailing zeros, but keep the currency's usual decimals ("3" → "3.00").
  let end = fraction.length;
  while (end > minFractionDigits && fraction[end - 1] === "0") end--;
  return { whole, fraction: fraction.slice(0, end) };
}

// Joins the segments as text before one Number() so no float drift creeps in.
function parseSegments({ whole, fraction }: AmountSegments): number | null {
  if (whole === "" && fraction === "") return null;
  return Number(`${whole || "0"}.${fraction || "0"}`);
}

// Width in ch for a segment showing `text` or, while empty, `placeholder`.
function segmentWidth(text: string, placeholder: string): string {
  const chars = Math.max(text.length, placeholder.length, 1);
  // Same +4px as .opal-input-segment: DM Mono digit ink is a hair wider than 1ch.
  return `calc(${chars}ch + 4px)`;
}

// ---------------------------------------------------------------------------
// InputCurrency
// ---------------------------------------------------------------------------

interface InputCurrencyProps {
  /** The amount, or null when empty. */
  value: number | null;

  /** Fires with the committed amount, or null when cleared. */
  onChange: (value: number | null) => void;

  /**
   * ISO 4217 code. Sets the symbol, its side and the default decimals.
   * @default "USD"
   */
  currency?: string;

  /**
   * Most digits the fraction segment takes. Defaults to the currency's usual
   * decimals (USD 2, JPY 0); raise it for sub-cent rates. 0 hides the segment.
   */
  decimalPlaces?: number;

  /** Placeholders of the whole and fraction segments. */
  placeholder?: { whole?: string; fraction?: string };

  /** Error chrome. */
  error?: boolean;
  disabled?: boolean;

  /** Applied to the whole-number segment so a `<label htmlFor>` can target the field. */
  id?: string;
}

/**
 * InputCurrency: a segmented amount field (`$ [whole] . [fraction]`) on the
 * shared .opal-input chrome. The locale sets the symbol, its side and the
 * decimal separator. Typing commits on blur or Enter; an empty field commits
 * null.
 */
function InputCurrency({
  value,
  onChange,
  currency = "USD",
  decimalPlaces,
  placeholder,
  error,
  disabled,
  id,
}: InputCurrencyProps) {
  const strings = useOpalStrings();
  const parts = strings.inputCurrencyParts(currency);
  const maxFraction = Math.max(0, decimalPlaces ?? parts.fractionDigits);
  const minFraction = Math.min(parts.fractionDigits, maxFraction);
  const showFraction = maxFraction > 0;
  const wholePlaceholder = placeholder?.whole ?? "0";
  const fractionPlaceholder = placeholder?.fraction ?? "0".repeat(minFraction);

  const variant: InputVariants = disabled
    ? "disabled"
    : error
      ? "error"
      : "primary";

  const [segments, setSegments] = React.useState<AmountSegments>(() =>
    toSegments(value, maxFraction, minFraction)
  );

  const wholeRef = React.useRef<HTMLInputElement>(null);
  const fractionRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    setSegments(toSegments(value, maxFraction, minFraction));
  }, [value, maxFraction, minFraction]);

  function commit(next: AmountSegments) {
    const parsed = parseSegments(next);
    if (parsed !== value) {
      onChange(parsed);
    } else {
      // Same amount: normalise the display ("3.5" → "3.50").
      setSegments(toSegments(value, maxFraction, minFraction));
    }
  }

  const handleSegmentChange = makeSegmentChangeHandler(setSegments);
  const handleSegmentKeyDown = makeSegmentKeyDownHandler(segments, commit);

  // The whole segment splits on a decimal separator, so typing "." jumps to
  // the fraction and pasting "3.50" fills both segments.
  function handleWholeChange(e: React.ChangeEvent<HTMLInputElement>) {
    const raw = e.target.value;
    const separators = [parts.decimal, ...DECIMAL_KEYS];
    const index = Math.max(...separators.map((sep) => raw.indexOf(sep)));
    if (index < 0 || !showFraction) {
      setSegments((prev) => ({ ...prev, whole: raw.replace(/\D/g, "") }));
      return;
    }
    const whole = raw.slice(0, index).replace(/\D/g, "");
    const fraction = raw
      .slice(index + 1)
      .replace(/\D/g, "")
      .slice(0, maxFraction);
    setSegments((prev) => ({ whole, fraction: fraction || prev.fraction }));
    fractionRef.current?.focus();
    fractionRef.current?.select();
  }

  // Commit when focus leaves the whole field, not on intra-field moves.
  function handleRootBlur(e: React.FocusEvent<HTMLDivElement>) {
    if (e.currentTarget.contains(e.relatedTarget as Node)) return;
    commit(segments);
  }

  const symbol = <SegmentSeparator>{parts.symbol}</SegmentSeparator>;

  return (
    <div className="opal-input-segmented-root">
      <div
        role="presentation"
        className="opal-input opal-input-segmented"
        data-variant={variant}
        onBlur={handleRootBlur}
        // A click on the chrome, not on a segment, focuses the whole segment.
        onClick={(e) => {
          if (!(e.target instanceof HTMLInputElement)) {
            wholeRef.current?.focus();
          }
        }}
      >
        <div
          className="opal-input-segmented-content"
          role="group"
          aria-label={strings.inputCurrencyAmount}
        >
          {!parts.symbolAfter && symbol}
          {/* raw-ok: segmented numeric fields have no Opal input primitive. The field chrome is the surrounding .opal-input. */}
          <input
            {...SEGMENT_INPUT_PROPS}
            inputMode={showFraction ? "decimal" : "numeric"}
            disabled={disabled}
            ref={wholeRef}
            id={id}
            aria-label={strings.inputCurrencyWhole}
            placeholder={wholePlaceholder}
            value={segments.whole}
            style={{ width: segmentWidth(segments.whole, wholePlaceholder) }}
            onChange={handleWholeChange}
            onKeyDown={handleSegmentKeyDown(
              "whole",
              null,
              showFraction ? fractionRef : null
            )}
          />
          {showFraction && (
            <>
              <SegmentSeparator>{parts.decimal}</SegmentSeparator>
              {/* raw-ok: segmented numeric fields have no Opal input primitive. The field chrome is the surrounding .opal-input. */}
              <input
                {...SEGMENT_INPUT_PROPS}
                disabled={disabled}
                ref={fractionRef}
                aria-label={strings.inputCurrencyFraction}
                placeholder={fractionPlaceholder}
                value={segments.fraction}
                style={{
                  width: segmentWidth(segments.fraction, fractionPlaceholder),
                }}
                onChange={handleSegmentChange("fraction", maxFraction, null)}
                onKeyDown={handleSegmentKeyDown("fraction", wholeRef)}
              />
            </>
          )}
          {parts.symbolAfter && symbol}
        </div>
      </div>
    </div>
  );
}

export { InputCurrency, type InputCurrencyProps };
