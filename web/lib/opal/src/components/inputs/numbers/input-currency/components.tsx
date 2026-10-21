"use client";

import "@opal/components/inputs/shared.css";
import "@opal/components/inputs/numbers/input-currency/styles.css";
import React from "react";
import type {
  CurrencyCode,
  CurrencyPrecision,
  InputVariants,
} from "@opal/types";
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

// Negative, non-finite and exponent-sized values render empty.
// The value is a JS number, which reproduces any decimal of up to 15
// significant digits exactly; more would round in onChange.
const MAX_PRECISION = 15;

// "unlimited" and anything above 15 → 15; negatives → 0; fractions round
// down; NaN or no precision → the currency's usual decimals.
function resolvePrecision(
  precision: CurrencyPrecision | undefined,
  currencyDigits: number
): number {
  if (precision === "unlimited") return MAX_PRECISION;
  if (precision === undefined || Number.isNaN(precision)) return currencyDigits;
  return Math.min(MAX_PRECISION, Math.max(0, Math.floor(precision)));
}

// The shortest decimal that reads back as `value`, without an exponent:
// 0.075 → "0.075" (not toFixed's binary "0.0749…"), 1e-7 → "0.0000001".
function toPlainDecimal(value: number): string {
  const text = String(value);
  const match = /^(\d+)(?:\.(\d+))?e([+-]\d+)$/.exec(text);
  if (!match) return text;
  const [, intPart = "", fracPart = "", exponent = "0"] = match;
  const digits = intPart + fracPart;
  const point = intPart.length + Number(exponent);
  if (point <= 0) return `0.${"0".repeat(-point)}${digits}`;
  if (point >= digits.length) return digits + "0".repeat(point - digits.length);
  return `${digits.slice(0, point)}.${digits.slice(point)}`;
}

// Adds one to a digit string, carrying: "099" → "100", "99" → "100".
function incrementDigits(digits: string): string {
  const chars = digits.split("");
  for (let i = chars.length - 1; i >= 0; i--) {
    if (chars[i] !== "9") {
      chars[i] = String(Number(chars[i]) + 1);
      return chars.join("");
    }
    chars[i] = "0";
  }
  return `1${chars.join("")}`;
}

// Negative, non-finite and exponent-sized values render empty. Rounds half up
// on the decimal digits, so 0.075 at precision 2 shows 0.08.
function toSegments(
  value: number | null,
  precision: number,
  minFractionDigits: number
): AmountSegments {
  if (value == null || !Number.isFinite(value) || value < 0 || value >= 1e21) {
    return EMPTY_SEGMENTS;
  }
  let [whole = "", fraction = ""] = toPlainDecimal(value).split(".");
  if (fraction.length > precision) {
    const roundUp = (fraction[precision] ?? "0") >= "5";
    fraction = fraction.slice(0, precision);
    if (roundUp) {
      const carried = incrementDigits(whole + fraction);
      whole = carried.slice(0, carried.length - precision);
      fraction = carried.slice(carried.length - precision);
    }
  }
  // Keep the currency's usual decimals ("3" → "3.00"), drop other trailing zeros.
  fraction = fraction.padEnd(minFractionDigits, "0");
  let end = fraction.length;
  while (end > minFractionDigits && fraction[end - 1] === "0") end--;
  return { whole, fraction: fraction.slice(0, end) };
}

// Arabic-Indic (U+0660) and Extended Arabic-Indic (U+06F0) digits, which the
// Arabic locale types, read as their ASCII digits.
function toAsciiDigits(text: string): string {
  return text.replace(/[\u0660-\u0669\u06F0-\u06F9]/g, (digit) =>
    String((digit.charCodeAt(0) - 0x0660) % 0x90)
  );
}

// "0007" reads "7" and "0000" reads "0": leading zeros never change the amount.
function trimLeadingZeros(whole: string): string {
  return whole.replace(/^0+(?=\d)/, "");
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
  currency?: CurrencyCode;

  /**
   * Most digits the fraction segment accepts; typing more is blocked. Defaults
   * to the currency's usual decimals (USD and EUR 2, JPY 0). Clamped to an
   * integer in [0, 15]; `"unlimited"` is 15, the most digits a JS number
   * holds exactly. 0 hides the segment.
   */
  precision?: CurrencyPrecision;

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
  precision,
  placeholder,
  error,
  disabled,
  id,
}: InputCurrencyProps) {
  const strings = useOpalStrings();
  const parts = strings.inputCurrencyParts(currency);
  const maxFraction = resolvePrecision(precision, parts.fractionDigits);
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

  // Resync when the value differs from the draft, so the echo of our own
  // onChange never reformats the segment being typed in. A precision change
  // always rebuilds: the draft may hold digits the new precision hides.
  const precisionRef = React.useRef({ maxFraction, minFraction });
  React.useEffect(() => {
    const precisionChanged =
      precisionRef.current.maxFraction !== maxFraction ||
      precisionRef.current.minFraction !== minFraction;
    precisionRef.current = { maxFraction, minFraction };
    setSegments((prev) =>
      !precisionChanged && parseSegments(prev) === value
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

  // Inside a form, Enter tidies the display and submits from any segment, like
  // any text input (every draft is a valid amount). Outside a form, Enter steps
  // through the segments like Tab.
  function handleKeyDown(
    part: keyof AmountSegments,
    prevRef: React.RefObject<HTMLInputElement | null> | null,
    nextRef: React.RefObject<HTMLInputElement | null> | null
  ) {
    const shared = handleSegmentKeyDown(part, prevRef, nextRef);
    return (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key !== "Enter") return shared(e);
      const next = nextRef?.current;
      if (next && !e.currentTarget.form) {
        e.preventDefault();
        next.focus();
        next.select();
      } else {
        commit(segments);
      }
    };
  }

  // The whole segment splits on a decimal separator, so typing "." jumps to
  // the fraction and pasting "3.50" fills both segments.
  // Typing: the locale decimal key steps to the fraction; any other
  // non-digit, the grouping key included, does nothing.
  function handleWholeChange(e: React.ChangeEvent<HTMLInputElement>) {
    const raw = toAsciiDigits(e.target.value);
    const decimalAt = raw.indexOf(parts.decimal);
    if (decimalAt < 0) {
      update({ ...segments, whole: raw.replace(/\D/g, "") });
      return;
    }
    // No fraction segment: the decimal key is a no-op like any other.
    if (!showFraction) {
      update({ ...segments, whole: raw.replace(/\D/g, "") });
      return;
    }
    // Wherever the caret is, the separator splits the number there: digits
    // before it stay (an empty whole part is 0, so ".5" reads 0.5), and
    // digits after it move to the front of the fraction ("1|234" → 1 . 234).
    // Arrows, Tab and Enter only move focus and fill nothing.
    const whole = trimLeadingZeros(raw.slice(0, decimalAt).replace(/\D/g, ""));
    const moved = raw
      .slice(decimalAt + parts.decimal.length)
      .replace(/\D/g, "");
    update({
      whole: whole || "0",
      fraction: (moved + segments.fraction).slice(0, maxFraction),
    });
    const fraction = fractionRef.current;
    if (!fraction) return;
    fraction.focus();
    if (moved) {
      // Caret just after the separator, ahead of the moved digits.
      requestAnimationFrame(() => fraction.setSelectionRange(0, 0));
    } else {
      fraction.select();
    }
  }

  function handleFractionChange(e: React.ChangeEvent<HTMLInputElement>) {
    const fraction = toAsciiDigits(e.target.value)
      .replace(/\D/g, "")
      .slice(0, maxFraction);
    update({ ...segments, fraction });
  }

  // Pasting reads the text as an amount, whichever segment has focus. Only
  // whitespace, grouping and the currency's own symbol or code are dropped;
  // the rest must be digits with at most one decimal separator:
  // - one separator: whole and fraction both replaced ("1.2" → 1 . 2);
  // - none: the digits go into the focused segment at the caret;
  // - anything else ("a1b2c3", "1.2.3", "-5"): not an amount, so ignored.
  function handlePaste(segment: keyof AmountSegments) {
    return (e: React.ClipboardEvent<HTMLInputElement>) => {
      e.preventDefault();
      const text = [parts.symbol, currency, parts.group]
        .reduce(
          (rest, token) => rest.split(token).join(""),
          toAsciiDigits(e.clipboardData.getData("text"))
        )
        .replace(/\s/g, "");
      const pieces = text.split(parts.decimal);
      if (
        pieces.length > 2 ||
        pieces.some((piece) => /\D/.test(piece)) ||
        pieces.every((piece) => piece === "")
      ) {
        return;
      }

      const [first = "", second] = pieces;
      if (second !== undefined) {
        update({
          // A pasted separator implies the whole part, as typing one does.
          whole: trimLeadingZeros(first) || "0",
          fraction: showFraction ? second.slice(0, maxFraction) : "",
        });
        return;
      }

      const input = e.currentTarget;
      const start = input.selectionStart ?? input.value.length;
      const end = input.selectionEnd ?? start;
      const inserted =
        input.value.slice(0, start) + first + input.value.slice(end);
      const next =
        segment === "fraction" ? inserted.slice(0, maxFraction) : inserted;
      update({ ...segments, [segment]: next });
      const caret = Math.min(start + first.length, next.length);
      requestAnimationFrame(() => input.setSelectionRange(caret, caret));
    };
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
          {/* The number reads left to right on every page, like the digits it
              holds; the symbol outside it keeps the page's side. */}
          <span className="opal-input-currency-amount" dir="ltr">
            {/* raw-ok: segmented numeric fields have no Opal input primitive. The field chrome is the surrounding .opal-input. */}
            <input
              {...SEGMENT_INPUT_PROPS}
              inputMode={showFraction ? "decimal" : "numeric"}
              disabled={disabled}
              ref={wholeRef}
              // Tidy the whole segment as soon as focus leaves it, not only when
              // focus leaves the field.
              onBlur={() =>
                setSegments((prev) => ({
                  ...prev,
                  whole: trimLeadingZeros(prev.whole),
                }))
              }
              id={id}
              aria-label={strings.inputCurrencyWhole}
              placeholder={wholePlaceholder}
              value={segments.whole}
              style={{ width: segmentWidth(segments.whole, wholePlaceholder) }}
              onChange={handleWholeChange}
              onPaste={handlePaste("whole")}
              onKeyDown={handleKeyDown(
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
                  maxLength={maxFraction}
                  placeholder={fractionPlaceholder}
                  value={segments.fraction}
                  style={{
                    width: segmentWidth(segments.fraction, fractionPlaceholder),
                  }}
                  onChange={handleFractionChange}
                  onPaste={handlePaste("fraction")}
                  onKeyDown={handleKeyDown("fraction", wholeRef, null)}
                />
              </>
            )}
          </span>
          {parts.symbolAfter && symbol}
        </div>
      </div>
    </div>
  );
}

export { InputCurrency, type InputCurrencyProps };
