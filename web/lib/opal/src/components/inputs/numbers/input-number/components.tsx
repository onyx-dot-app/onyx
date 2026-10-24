"use client";

import * as React from "react";
import "@opal/components/inputs/shared.css";
import { cn } from "@opal/utils";
import { Button } from "@opal/components/buttons/button/components";
import { Text } from "@opal/components";
import { Interactive } from "@opal/core";
import { SvgChevronUp, SvgChevronDown, SvgRevert } from "@opal/icons";

type InputNumberVariant =
  | "primary"
  | "internal"
  | "error"
  | "disabled"
  | "readOnly";

// Inner text colour per variant; the wrapper chrome is the shared .opal-input.
// The font and the placeholder style are the same in every variant, so the
// field keeps its height when it turns to the error state.
const INNER_CLASSES: Record<InputNumberVariant, string | null> = {
  primary: "text-text-04",
  internal: "text-text-04",
  error: "text-text-04",
  disabled: "text-text-01",
  readOnly: "text-text-01",
};

/**
 * InputNumber Component
 *
 * A number input with increment/decrement stepper buttons and optional reset.
 *
 * @example
 * ```tsx
 * // Basic usage
 * <InputNumber
 *   value={count}
 *   onChange={setCount}
 *   min={0}
 *   max={100}
 * />
 *
 * // With reset button
 * <InputNumber
 *   value={count}
 *   onChange={setCount}
 *   defaultValue={10}
 *   showReset
 * />
 *
 * // With step
 * <InputNumber
 *   value={count}
 *   onChange={setCount}
 *   step={5}
 * />
 * ```
 */
export interface InputNumberProps {
  value: number | null;
  onChange: (value: number | null) => void;
  min?: number;
  max?: number;
  step?: number;
  decimalPlaces?: number;
  defaultValue?: number;
  showReset?: boolean;
  variant?: InputNumberVariant;
  disabled?: boolean;
  placeholder?: string;
  /** Unit text shown after the value, inside the field (e.g. "minutes"). */
  suffix?: string;
  /** Applied to the input so a `<label htmlFor>` can target it. */
  id?: string;
  /** Whether leaving the field blank commits `null`. When false, a blank field gets its value back on blur. */
  allowEmpty?: boolean;
  /** A plain type-in field: no stepper buttons, the value in mono and the unit in `text-02`. */
  plain?: boolean;
}

/**
 * The text to show for `value`. Text that already reads as `value` stays as
 * typed: `String(value)` would show a long number in exponent form or
 * rounded ("1e+35" for 35 nines).
 */
function textFor(value: number | null, typed: string): string {
  if (value === null) return "";
  return typed.trim() !== "" && Number(typed) === value ? typed : String(value);
}

export default function InputNumber({
  value,
  onChange,
  min,
  max,
  step = 1,
  decimalPlaces = 0,
  defaultValue,
  showReset = false,
  variant = "primary",
  disabled = false,
  placeholder,
  suffix,
  id,
  allowEmpty = true,
  plain = false,
}: InputNumberProps) {
  const inputRef = React.useRef<HTMLInputElement | null>(null);
  const [inputValue, setInputValue] = React.useState(
    value === null ? "" : String(value)
  );
  const isDisabled = disabled || variant === "disabled";
  // A negative lower bound lets the value start with a minus sign. A lone
  // "-" is a value still being typed, so it never reaches onChange.
  const allowsNegative: boolean = min !== undefined && min < 0;
  const inputPattern: string =
    (allowsNegative ? "-?" : "") +
    (decimalPlaces === 0 ? "[0-9]*" : `[0-9]*[.]?[0-9]{0,${decimalPlaces}}`);

  // Sync input value when external value changes (e.g., from stepper buttons or reset)
  React.useEffect(() => {
    setInputValue((typed) => textFor(value, typed));
  }, [value]);

  const effectiveValue = value ?? 0;
  const canIncrement = max === undefined || effectiveValue < max;
  const canDecrement =
    value !== null && (min === undefined || effectiveValue > min);
  const canReset =
    showReset && defaultValue !== undefined && value !== defaultValue;
  const normalizePrecision = (newValue: number) =>
    Number(newValue.toFixed(decimalPlaces));

  const handleIncrement = () => {
    if (canIncrement) {
      const newValue = normalizePrecision(effectiveValue + step);
      onChange(max !== undefined ? Math.min(newValue, max) : newValue);
    }
  };

  const handleDecrement = () => {
    if (canDecrement) {
      const newValue = normalizePrecision(effectiveValue - step);
      onChange(min !== undefined ? Math.max(newValue, min) : newValue);
    }
  };

  const handleReset = () => {
    if (defaultValue !== undefined) {
      onChange(defaultValue);
    }
  };

  // Whether the text was typed into since the field took focus. Blur clamps
  // only a typed value, so a stored value outside the bounds stays as is.
  const typedRef = React.useRef(false);

  const handleBlur = () => {
    const typed: boolean = typedRef.current;
    typedRef.current = false;
    if (inputValue.trim() === "" && !allowEmpty) {
      setInputValue(value === null ? "" : String(value));
    } else if (inputValue.trim() === "") {
      // Kept as null so the placeholder shows.
      onChange(null);
    } else if (typed && value !== null && min !== undefined && value < min) {
      // Typing is free; leaving the field clamps to the nearest bound.
      onChange(min);
      setInputValue(String(min));
    } else if (typed && value !== null && max !== undefined && value > max) {
      onChange(max);
      setInputValue(String(max));
    } else {
      setInputValue((typed) => textFor(value, typed));
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const rawValue = e.target.value;

    if (rawValue !== "" && !new RegExp(`^${inputPattern}$`).test(rawValue)) {
      return;
    }

    setInputValue(rawValue);
    typedRef.current = true;

    // Allow empty input while typing (fallback applied on blur)
    if (rawValue === "") {
      return;
    }

    const val = Number(rawValue);
    if (!Number.isFinite(val)) {
      return;
    }
    // Typed values are not clamped while typing, so a partial value (the "0"
    // of "0.5") or a long one is kept as typed; blur clamps to the bounds.
    onChange(val);
  };

  return (
    // Pointer convenience only — this forwards a click to the input, which is
    // already keyboard reachable.
    <div
      role="presentation"
      className="opal-input"
      data-variant={variant}
      onClick={() => inputRef.current?.focus()}
    >
      <input
        ref={inputRef}
        id={id}
        type="text"
        // Numeric soft keyboards have no minus key.
        inputMode={
          allowsNegative
            ? undefined
            : decimalPlaces === 0
              ? "numeric"
              : "decimal"
        }
        pattern={inputPattern}
        disabled={isDisabled}
        value={inputValue}
        placeholder={placeholder}
        aria-invalid={variant === "error" || undefined}
        onChange={handleInputChange}
        onBlur={handleBlur}
        className={cn(
          "w-full h-6 bg-transparent p-0.5 focus:outline-hidden disabled:cursor-not-allowed placeholder:!font-main-ui-muted placeholder:text-text-02",
          plain ? "font-main-ui-mono" : "font-main-ui-body",
          INNER_CLASSES[variant]
        )}
      />

      <div className="flex flex-row items-center gap-1">
        {suffix && (
          // The placeholder's style: muted weight in text-02.
          <Text font="main-ui-muted" color={isDisabled ? "text-01" : "text-02"}>
            {suffix}
          </Text>
        )}
        {showReset && (
          <Button
            disabled={!canReset || isDisabled}
            icon={SvgRevert}
            onClick={handleReset}
            prominence="tertiary"
          />
        )}
        {!plain && (
          // The two steppers share the text line's height (1.5rem), so the
          // field stays as tall as the other inputs. Each arrow moves 0.5px
          // toward the other, so the chevrons sit 8px apart.
          <div className="flex flex-col h-6">
            <div className="flex flex-1 items-end justify-center translate-y-[0.5px]">
              <Interactive.Stateless
                prominence="tertiary"
                disabled={!canIncrement || isDisabled}
                onClick={handleIncrement}
              >
                <Interactive.Container type="button" size="fit" rounding={1}>
                  <SvgChevronUp
                    size={12}
                    className="interactive-foreground-icon"
                  />
                </Interactive.Container>
              </Interactive.Stateless>
            </div>
            <div className="flex flex-1 items-start justify-center -translate-y-[0.5px]">
              <Interactive.Stateless
                prominence="tertiary"
                disabled={!canDecrement || isDisabled}
                onClick={handleDecrement}
              >
                <Interactive.Container type="button" size="fit" rounding={1}>
                  <SvgChevronDown
                    size={12}
                    className="interactive-foreground-icon"
                  />
                </Interactive.Container>
              </Interactive.Stateless>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
