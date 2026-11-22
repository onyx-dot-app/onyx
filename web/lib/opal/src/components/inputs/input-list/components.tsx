"use client";

import { useState, KeyboardEvent } from "react";
import InputTypeIn from "@opal/components/inputs/texts/input-type-in/components";
import { Tag } from "@opal/components/tag/components";
import type { RichStr } from "@opal/types";
import { useInputDisabled } from "@opal/components/inputs/disabled";

export interface InputListProps {
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  error?: boolean;
  /** Shown on hover, in any state. A disabled row's reason replaces it. */
  tooltip?: string | RichStr;
}

/**
 * InputList is a component that allows the user to input a list of values by typing and pressing Enter.
 * It displays the values in a list of chips, and allows the user to add and remove values.

 * @param values - The array of values to display in the input field.
 * @param onChange - The function to call when the value changes.
 * @param placeholder - The placeholder text to display in the input field.
 * @param disabled - Whether the input field is disabled.
 *
 * Inside `InputHorizontal` or `InputVertical`, the row's `disabled` and
 * `disabledTooltip` apply to it too. The text field shows `tooltip`.
 **/
export function InputList({
  values,
  onChange,
  placeholder = "",
  disabled: disabledProp,
  error = false,
  tooltip,
}: InputListProps) {
  const disabled = useInputDisabled(disabledProp);
  const [inputValue, setInputValue] = useState("");

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !e.nativeEvent.isComposing && inputValue.trim()) {
      e.preventDefault();
      const trimmedValue = inputValue.trim();

      // Avoid duplicates
      if (!values.includes(trimmedValue)) {
        onChange([...values, trimmedValue]);
      }

      setInputValue("");
    }
  }

  function removeValue(indexToRemove: number) {
    onChange(values.filter((_, index) => index !== indexToRemove));
  }

  return (
    <div className="flex flex-col w-full space-y-2 mb-4">
      <InputTypeIn
        placeholder={placeholder}
        value={inputValue}
        tooltip={tooltip}
        variant={disabled ? "disabled" : error ? "error" : undefined}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyDown={handleKeyDown}
      />

      <div className="mt-3">
        <div className="flex flex-wrap gap-1.5">
          {values.map((value, index) => (
            <Tag
              key={index}
              title={value}
              disabled={disabled}
              onRemove={() => removeValue(index)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
