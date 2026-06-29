"use client";

/**
 * InputComboBoxMulti - Multi-select built on top of {@link InputComboBox}.
 *
 * Reuses InputComboBox's filtering, keyboard navigation, and dropdown UI, but
 * tracks an array of selected options instead of a single value. Selected
 * options render as removable chips; the wrapped input stays empty so it is
 * always ready for the next pick (and the dropdown stays open between picks).
 *
 * Set `creatable` (with `onCreate`) to let users add options that don't exist
 * yet — `onCreate` resolves to the persisted option, which is then selected.
 *
 * @example
 * ```tsx
 * <InputComboBoxMulti
 *   placeholder="Select categories"
 *   options={options}
 *   selected={selected}
 *   onChange={setSelected}
 *   creatable
 *   onCreate={async (label) => await createCategory(label)}
 * />
 * ```
 */

import { useCallback } from "react";
import Chip from "@/refresh-components/Chip";
import { FieldMessage } from "../../messages/FieldMessage";
import InputComboBox from "./InputComboBox";
import { ComboBoxOption } from "./types";

interface InputComboBoxMultiProps {
  /** Currently selected options. */
  selected: ComboBoxOption[];
  /** Options available to pick from. Already-selected options are hidden. */
  options: ComboBoxOption[];
  /** Called with the next selection whenever an option is added or removed. */
  onChange: (selected: ComboBoxOption[]) => void;
  placeholder: string;
  disabled?: boolean;
  /** When true, users can create options not present in `options` via `onCreate`. */
  creatable?: boolean;
  /** Persists a newly-typed option and resolves to it (or null to abort). */
  onCreate?: (label: string) => Promise<ComboBoxOption | null>;
  /** Field name for accessibility. */
  name?: string;
  /** Error message rendered below the input. */
  error?: string;
}

export default function InputComboBoxMulti({
  selected,
  options,
  onChange,
  placeholder,
  disabled = false,
  creatable = false,
  onCreate,
  name,
  error,
}: InputComboBoxMultiProps) {
  const isSelected = useCallback(
    (value: string) => selected.some((option) => option.value === value),
    [selected]
  );

  const availableOptions = options.filter(
    (option) => !isSelected(option.value)
  );

  const handleSelect = useCallback(
    async (value: string) => {
      const existing = options.find((option) => option.value === value);
      if (existing) {
        if (!isSelected(existing.value)) {
          onChange([...selected, existing]);
        }
        return;
      }

      if (!creatable || !onCreate) return;
      const created = await onCreate(value);
      if (created && !isSelected(created.value)) {
        onChange([...selected, created]);
      }
    },
    [options, selected, isSelected, onChange, creatable, onCreate]
  );

  const handleRemove = useCallback(
    (value: string) => {
      onChange(selected.filter((option) => option.value !== value));
    },
    [selected, onChange]
  );

  return (
    <div className="flex flex-col gap-2">
      <InputComboBox
        value=""
        onValueChange={handleSelect}
        options={availableOptions}
        strict={!creatable}
        disabled={disabled}
        placeholder={placeholder}
        name={name}
        isError={!!error}
        createPrefix={creatable ? "Create" : undefined}
      />

      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selected.map((option) => (
            <Chip
              key={option.value}
              onRemove={() => handleRemove(option.value)}
            >
              {option.label}
            </Chip>
          ))}
        </div>
      )}

      {error && (
        <FieldMessage variant="error" className="ml-0.5">
          <FieldMessage.Content role="alert">{error}</FieldMessage.Content>
        </FieldMessage>
      )}
    </div>
  );
}
