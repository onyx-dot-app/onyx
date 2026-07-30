"use client";

import "@opal/components/inputs/shared.css";
// The inner field reuses InputTypeIn's .opal-input-field styling.
import "@opal/components/inputs/input-type-in/styles.css";
import "@opal/components/inputs/input-tags/styles.css";
import { useRef } from "react";
import type { IconFunctionComponent } from "@opal/types";
import { Button, Tag, TAG_REMOVE_CLASS } from "@opal/components";
import { SvgX } from "@opal/icons";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TagItem {
  id: string;
  label: string;

  /** Shows the warning indicator on the tag. */
  error?: boolean;
}

interface InputTagsProps {
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
}

// ---------------------------------------------------------------------------
// InputTags
// ---------------------------------------------------------------------------

/**
 * Chips-in-input (Figma `Input/Tags`): editable Tags inline with a text
 * input. Enter adds the trimmed text. Backspace on an empty input arms the
 * last tag (its dark keyboard-selection state), and Backspace or Delete on
 * an armed tag removes it and returns focus to the input.
 */
function InputTags({
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
}: InputTagsProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

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
      className="opal-input opal-input-tags"
      data-variant={disabled ? "disabled" : variant}
      onKeyDown={handleRootKeyDown}
      onClick={() => inputRef.current?.focus()}
    >
      {Icon && (
        <div className="opal-input-tags-icon-container">
          <Icon className="opal-input-tags-icon" />
        </div>
      )}
      <div className="opal-input-tags-tags">
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
          className="opal-input-field opal-input-tags-field"
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
          tooltip="Clear"
          onClick={(event) => {
            event.stopPropagation();
            onClear();
          }}
        />
      )}
    </div>
  );
}

export { InputTags, type InputTagsProps, type TagItem };
