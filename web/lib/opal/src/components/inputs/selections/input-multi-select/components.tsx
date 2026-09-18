"use client";

import "@opal/components/inputs/shared.css";
// The inner field reuses InputTypeIn's .opal-input-field styling.
import "@opal/components/inputs/input-type-in/styles.css";
import "@opal/components/inputs/selections/input-multi-select/styles.css";
import { useEffect, useRef } from "react";
import type { IconFunctionComponent } from "@opal/types";
import { Button, Tag, TAG_REMOVE_CLASS } from "@opal/components";
import { SvgX } from "@opal/icons";
import { useOpalStrings } from "@opal/strings";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TagItem {
  id: string;
  label: string;

  /** Shows the warning indicator on the tag. */
  error?: boolean;
}

interface InputMultiSelectProps {
  /** Tags rendered before the text input. */
  tags: TagItem[];

  onRemoveTag: (id: string) => void;

  /** Called with the trimmed input text on Enter (no-op when empty). */
  onAdd: (value: string) => void;

  /** Controlled input text. */
  value: string;

  onChange: (value: string) => void;

  placeholder?: string;

  /**
   * Wrapper chrome variant. `"internal"` is the borderless Figma
   * `Style=Subtle` look.
   */
  variant?: "primary" | "internal" | "error";

  /** Dims the field, disables the input, hides the remove and clear buttons. */
  disabled?: boolean;

  /** Leading icon. */
  icon?: IconFunctionComponent;

  /** Renders the clear action button (Figma `Clear`). */
  onClear?: () => void;

  /** Tag rows the field is tall enough to show before it grows. */
  minRows?: number;

  /** Focuses the text input on mount. */
  focusOnMount?: boolean;
}

// ---------------------------------------------------------------------------
// InputMultiSelect
// ---------------------------------------------------------------------------

/**
 * Chips-in-input (Figma `Input/Tags`): editable Tags inline with a text
 * input. Enter adds the trimmed text. Backspace on an empty input arms the
 * last tag (its dark keyboard-selection state), and Backspace or Delete on
 * an armed tag removes it and returns focus to the input.
 */
function InputMultiSelect({
  tags,
  onRemoveTag,
  onAdd,
  value,
  onChange,
  placeholder,
  variant = "primary",
  disabled = false,
  icon: Icon,
  onClear,
  minRows = 1,
  focusOnMount = false,
}: InputMultiSelectProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const strings = useOpalStrings();

  useEffect(() => {
    if (focusOnMount) inputRef.current?.focus();
    // Mount only: later prop changes must not steal focus back.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleInputKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    // During IME composition, Enter confirms the candidate and Backspace
    // edits the composition. Neither may add or arm tags.
    if (event.nativeEvent.isComposing) return;
    if (event.key === "Enter") {
      event.preventDefault();
      event.stopPropagation();
      const trimmed = value.trim();
      if (trimmed) onAdd(trimmed);
      return;
    }
    if (event.key === "Backspace" && value === "" && tags.length > 0) {
      event.preventDefault();
      const removes = rootRef.current?.querySelectorAll<HTMLButtonElement>(
        `.${TAG_REMOVE_CLASS}`
      );
      removes?.[removes.length - 1]?.focus();
    }
  }

  // Backspace/Delete on an armed remove button deletes its tag. Enter and
  // Space already work as native button activation.
  function handleRootKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Backspace" && event.key !== "Delete") return;
    const target = event.target as HTMLElement;
    if (!target.classList.contains(TAG_REMOVE_CLASS)) return;
    event.preventDefault();
    target.click();
  }

  return (
    <div
      ref={rootRef}
      role="presentation"
      className="opal-input opal-input-multi-select"
      data-variant={disabled ? "disabled" : variant}
      onKeyDown={handleRootKeyDown}
      onClick={() => inputRef.current?.focus()}
    >
      {Icon && (
        <div className="opal-input-multi-select-icon-container">
          <Icon className="opal-input-multi-select-icon" />
        </div>
      )}
      <div
        className="opal-input-multi-select-tags"
        data-multi-row={minRows > 1 || undefined}
        style={
          minRows > 1
            ? ({
                "--opal-input-multi-select-rows": minRows,
              } as React.CSSProperties)
            : undefined
        }
      >
        {tags.map((tag) => (
          <Tag
            key={tag.id}
            size="md"
            title={tag.label}
            error={tag.error}
            disabled={disabled}
            onRemove={() => {
              onRemoveTag(tag.id);
              inputRef.current?.focus();
            }}
          />
        ))}
        {/* raw-ok: nesting InputTypeIn double-pads the composite chrome, so the inner field reuses InputTypeIn's .opal-input-field styling directly */}
        <input
          ref={inputRef}
          type="text"
          className="opal-input-field opal-input-multi-select-field"
          disabled={disabled}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleInputKeyDown}
          placeholder={placeholder}
        />
      </div>
      {onClear !== undefined && !disabled && (
        <Button
          prominence="internal"
          icon={SvgX}
          size="xs"
          tooltip={strings.clear}
          onClick={(event) => {
            event.stopPropagation();
            onClear();
          }}
        />
      )}
    </div>
  );
}

export { InputMultiSelect, type InputMultiSelectProps, type TagItem };
