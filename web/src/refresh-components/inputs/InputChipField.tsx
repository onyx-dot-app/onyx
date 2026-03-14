"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import Chip from "@/refresh-components/Chip";
import {
  innerClasses,
  textClasses,
  Variants,
  wrapperClasses,
} from "@/refresh-components/inputs/styles";
import { SvgAlertTriangle } from "@opal/icons";
import type { IconProps } from "@opal/types";

export interface ChipItem {
  id: string;
  label: string;
  /** When true the chip shows a warning icon */
  error?: boolean;
}

export interface InputChipFieldProps {
  chips: ChipItem[];
  onRemoveChip: (id: string) => void;
  onAdd: (value: string) => void;

  value: string;
  onChange: (value: string) => void;

  placeholder?: string;
  disabled?: boolean;
  variant?: Variants;
  icon?: React.FunctionComponent<IconProps>;
  className?: string;
  /** "inline" renders chips and input in one row; "stacked" puts chips above the input */
  layout?: "inline" | "stacked";
}

/**
 * A tag/chip input field that renders chips inline alongside a text input.
 *
 * Pressing Enter adds a chip via `onAdd`. Pressing Backspace on an empty
 * input removes the last chip. Each chip has a remove button.
 *
 * @example
 * ```tsx
 * <InputChipField
 *   chips={[{ id: "1", label: "Search" }]}
 *   onRemoveChip={(id) => remove(id)}
 *   onAdd={(value) => add(value)}
 *   value={inputValue}
 *   onChange={setInputValue}
 *   placeholder="Add labels..."
 *   icon={SvgTag}
 * />
 * ```
 */
function InputChipField({
  chips,
  onRemoveChip,
  onAdd,
  value,
  onChange,
  placeholder,
  disabled = false,
  variant = "primary",
  icon: Icon,
  className,
  layout = "inline",
}: InputChipFieldProps) {
  const inputRef = React.useRef<HTMLInputElement>(null);

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (disabled) {
      return;
    }

    if (e.key === "Enter") {
      e.preventDefault();
      e.stopPropagation();
      const trimmed = value.trim();
      if (trimmed) {
        onAdd(trimmed);
      }
    }
    if (e.key === "Backspace" && value === "") {
      const lastChip = chips[chips.length - 1];
      if (lastChip) {
        onRemoveChip(lastChip.id);
      }
    }
  }

  const chipElements =
    chips.length > 0
      ? chips.map((chip) => (
          <Chip
            key={chip.id}
            onRemove={disabled ? undefined : () => onRemoveChip(chip.id)}
            rightIcon={
              chip.error
                ? (props) => (
                    <SvgAlertTriangle
                      {...props}
                      className="text-status-warning-text"
                    />
                  )
                : undefined
            }
            smallLabel={layout === "stacked"}
          >
            {chip.label}
          </Chip>
        ))
      : null;

  const inputElement = (
    <>
      {Icon && <Icon size={16} className="text-text-04 shrink-0" />}
      <input
        ref={inputRef}
        type="text"
        disabled={disabled}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        className={cn(
          "flex-1 min-w-[80px] h-[1.5rem] bg-transparent p-0.5 focus:outline-none",
          innerClasses[variant],
          textClasses[variant]
        )}
      />
    </>
  );

  return (
    <div
      className={cn(
        "flex p-1.5 rounded-08 cursor-text w-full",
        layout === "stacked"
          ? "flex-col gap-1"
          : "flex-row flex-wrap items-center gap-1",
        wrapperClasses[variant],
        className
      )}
      onClick={() => inputRef.current?.focus()}
    >
      {layout === "stacked" ? (
        <>
          {chipElements && (
            <div className="flex flex-row items-center flex-wrap gap-1">
              {chipElements}
            </div>
          )}
          <div className="flex flex-row items-center gap-1">{inputElement}</div>
        </>
      ) : (
        <>
          {chipElements}
          {inputElement}
        </>
      )}
    </div>
  );
}

export default InputChipField;
