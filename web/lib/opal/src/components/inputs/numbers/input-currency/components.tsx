"use client";

import "@opal/components/inputs/shared.css";
import "@opal/components/inputs/numbers/input-currency/styles.css";
import React from "react";
import type { InputVariants } from "@opal/types";
import {
  SEGMENT_INPUT_PROPS,
  SegmentSeparator,
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

  /** Fires on each edit with the amount, or null when cleared. */
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
 * decimal separator. Edits report through onChange as they happen (an empty
 * field reports null); blur and Enter tidy the display.
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

  // Resync only when the value differs from the draft, so the echo of our own
  // onChange never reformats the segment being typed in.
  React.useEffect(() => {
    setSegments((prev) =>
      parseSegments(prev) === value
        ? prev
        : toSegments(value, maxFraction, minFraction)
    );
  }, [value, maxFraction, minFraction]);

  // Every draft is a valid amount, so edits report at once.
  function update(next: AmountSegments) {
    setSegments(next);
    const parsed = parseSegments(next);
    if (parsed !== value) onChange(parsed);
  }

  // Blur and Enter tidy the display ("3.5" → "3.50").
  function commit(next: AmountSegments) {
    setSegments(toSegments(parseSegments(next), maxFraction, minFraction));
  }

  const handleSegmentKeyDown = makeSegmentKeyDownHandler(segments, commit);

  // The whole segment splits on a decimal separator, so typing "." jumps to
  // the fraction and pasting "3.50" fills both segments.
  function handleWholeChange(e: React.ChangeEvent<HTMLInputElement>) {
    const raw = e.target.value;
    const separators = [parts.decimal, ...DECIMAL_KEYS];
    const index = Math.max(...separators.map((sep) => raw.indexOf(sep)));
    if (index < 0 || !showFraction) {
      update({ ...segments, whole: raw.replace(/\D/g, "") });
      return;
    }
    const whole = raw.slice(0, index).replace(/\D/g, "");
    const fraction = raw
      .slice(index + 1)
      .replace(/\D/g, "")
      .slice(0, maxFraction);
    update({ whole, fraction: fraction || segments.fraction });
    fractionRef.current?.focus();
    fractionRef.current?.select();
  }

  function handleFractionChange(e: React.ChangeEvent<HTMLInputElement>) {
    const fraction = e.target.value.replace(/\D/g, "").slice(0, maxFraction);
    update({ ...segments, fraction });
  }

  // Tidy when focus leaves the whole field, not on intra-field moves.
  function handleRootBlur(e: React.FocusEvent<HTMLDivElement>) {
    if (e.currentTarget.contains(e.relatedTarget as Node)) return;
    commit(segments);
  }

  const symbol = <SegmentSeparator>{parts.symbol}</SegmentSeparator>;

  return (
    <div className="opal-input-segmented-root opal-input-currency">
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
                onChange={handleFractionChange}
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
