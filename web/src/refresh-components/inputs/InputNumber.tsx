"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { Button } from "@opal/components";
import {
  Variants,
  wrapperClasses,
  innerClasses,
  textClasses,
} from "@/refresh-components/inputs/styles";
import { SvgChevronUp, SvgChevronDown, SvgRevert } from "@opal/icons";

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
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  defaultValue?: number;
  showReset?: boolean;
  variant?: Variants;
  disabled?: boolean;
  className?: string;
}

export default function InputNumber({
  value,
  onChange,
  min,
  max,
  step = 1,
  defaultValue,
  showReset = false,
  variant = "primary",
  disabled = false,
  className,
}: InputNumberProps) {
  const inputRef = React.useRef<HTMLInputElement | null>(null);
  const [inputValue, setInputValue] = React.useState(String(value));
  const isDisabled = disabled || variant === "disabled";

  // Sync input value when external value changes (e.g., from stepper buttons or reset)
  React.useEffect(() => {
    setInputValue(String(value));
  }, [value]);

  const canIncrement = max === undefined || value < max;
  const canDecrement = min === undefined || value > min;
  const canReset =
    showReset && defaultValue !== undefined && value !== defaultValue;

  const handleIncrement = () => {
    if (canIncrement) {
      const newValue = value + step;
      onChange(max !== undefined ? Math.min(newValue, max) : newValue);
    }
  };

  const handleDecrement = () => {
    if (canDecrement) {
      const newValue = value - step;
      onChange(min !== undefined ? Math.max(newValue, min) : newValue);
    }
  };

  const handleReset = () => {
    if (defaultValue !== undefined) {
      onChange(defaultValue);
    }
  };

  const handleBlur = () => {
    // On blur, if empty, set fallback value; otherwise sync display with actual value
    if (inputValue.trim() === "") {
      let fallback = min ?? 0;
      if (max !== undefined) fallback = Math.min(fallback, max);
      setInputValue(String(fallback));
      onChange(fallback);
    } else {
      setInputValue(String(value));
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const rawValue = e.target.value;

    // Only allow digits (and empty string)
    if (rawValue !== "" && !/^\d+$/.test(rawValue)) {
      return;
    }

    setInputValue(rawValue);

    // Allow empty input while typing (fallback applied on blur)
    if (rawValue === "") {
      return;
    }

    const val = parseInt(rawValue, 10);
    let newValue = val;
    if (min !== undefined) newValue = Math.max(newValue, min);
    if (max !== undefined) newValue = Math.min(newValue, max);
    onChange(newValue);
  };

  return (
    <div
      className={cn(
        "flex flex-row items-center justify-between w-full h-fit pr-1.5 pl-1.5 rounded-08",
        wrapperClasses[variant],
        className
      )}
      onClick={() => inputRef.current?.focus()}
    >
      <input
        ref={inputRef}
        type="text"
        inputMode="numeric"
        pattern="[0-9]*"
        disabled={isDisabled}
        value={inputValue}
        onChange={handleInputChange}
        onBlur={handleBlur}
        className={cn(
          "w-full h-[1.5rem] bg-transparent p-0.5 focus:outline-none",
          innerClasses[variant],
          textClasses[variant]
        )}
      />

      <div className="flex flex-row items-center gap-1">
        {showReset && (
          <Button
            icon={SvgRevert}
            onClick={handleReset}
            disabled={!canReset || isDisabled}
            prominence="tertiary"
            size="sm"
          />
        )}
        <div className="flex flex-col">
          <button
            type="button"
            onClick={handleIncrement}
            disabled={!canIncrement || isDisabled}
            className="p-0.5 text-text-03 hover:text-text-04 disabled:text-text-02 disabled:cursor-not-allowed transition-colors"
          >
            <SvgChevronUp size={14} />
          </button>
          <button
            type="button"
            onClick={handleDecrement}
            disabled={!canDecrement || isDisabled}
            className="p-0.5 text-text-03 hover:text-text-04 disabled:text-text-02 disabled:cursor-not-allowed transition-colors"
          >
            <SvgChevronDown size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
