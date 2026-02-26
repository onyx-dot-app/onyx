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
import type { IconProps } from "@opal/types";

export interface ChipItem {
  id: string;
  label: string;
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

  return (
    <div
      className={cn(
        "flex flex-row items-center flex-wrap gap-1 p-1.5 rounded-08 cursor-text w-full",
        wrapperClasses[variant],
        className
      )}
      onClick={() => inputRef.current?.focus()}
    >
      {Icon && <Icon size={16} className="text-text-04 shrink-0" />}
      {chips.map((chip) => (
        <Chip
          key={chip.id}
          onRemove={disabled ? undefined : () => onRemoveChip(chip.id)}
          smallLabel={false}
        >
          {chip.label}
        </Chip>
      ))}
      <input
        ref={inputRef}
        type="text"
        disabled={disabled}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={chips.length === 0 ? placeholder : undefined}
        className={cn(
          "flex-1 min-w-[80px] h-[1.5rem] bg-transparent p-0.5 focus:outline-none",
          innerClasses[variant],
          textClasses[variant]
        )}
      />
    </div>
  );
}

export default InputChipField;
