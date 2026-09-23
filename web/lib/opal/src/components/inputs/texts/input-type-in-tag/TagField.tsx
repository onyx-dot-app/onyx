"use client";

import "@opal/components/inputs/shared.css";
// The inner field reuses InputTypeIn's .opal-input-field styling.
import "@opal/components/inputs/texts/input-type-in/styles.css";
import "@opal/components/inputs/texts/input-type-in-tag/styles.css";
import { useCallback, useEffect, useRef } from "react";
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

/** The props every chips-in-input field exposes to its callers. */
interface TagFieldBaseProps {
  /** Tags rendered before the text input. */
  tags: TagItem[];

  onRemoveTag: (id: string) => void;

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

/** The hooks a select needs to mount its dropdown on the field. */
interface TagFieldProps extends TagFieldBaseProps {
  /** Receives the wrapper element (a select's floating reference). */
  rootRef?: (node: HTMLDivElement | null) => void;

  /** The text input, when the caller must focus or read it. */
  inputRef?: React.RefObject<HTMLInputElement | null>;

  /**
   * Runs before the field's own Enter and Backspace handling. Calling
   * `preventDefault` claims the key.
   */
  onInputKeyDown?: (event: React.KeyboardEvent<HTMLInputElement>) => void;

  /** Enter with non-empty trimmed text, unless `onInputKeyDown` claimed it. */
  onEnter?: (trimmed: string) => void;

  onInputFocus?: () => void;

  onInputClick?: () => void;

  /** Extra attributes on the text input (a select's combobox aria). */
  inputAriaProps?: React.AriaAttributes & { role?: React.AriaRole };

  /** Trailing controls after the clear button (a select's chevron and dropdown). */
  children?: React.ReactNode;
}

// ---------------------------------------------------------------------------
// TagField
// ---------------------------------------------------------------------------

/**
 * The chips-in-input chrome (Figma `Input/Tags`) that `InputTypeInTag` and
 * `InputMultiSelect` share: editable `Tag`s inline with a text input on the
 * `.opal-input` chrome. Backspace on an empty input arms the last tag, and
 * Backspace or Delete on an armed tag removes it. Internal to Opal.
 */
function TagField({
  tags,
  onRemoveTag,
  value,
  onChange,
  placeholder,
  variant = "primary",
  disabled = false,
  icon: Icon,
  onClear,
  minRows = 1,
  focusOnMount = false,
  rootRef,
  inputRef: inputRefProp,
  onInputKeyDown,
  onEnter,
  onInputFocus,
  onInputClick,
  inputAriaProps,
  children,
}: TagFieldProps) {
  const strings = useOpalStrings();
  const ownRootRef = useRef<HTMLDivElement>(null);
  const ownInputRef = useRef<HTMLInputElement>(null);
  const inputRef = inputRefProp ?? ownInputRef;

  const setRootRef = useCallback(
    (node: HTMLDivElement | null) => {
      ownRootRef.current = node;
      rootRef?.(node);
    },
    [rootRef]
  );

  useEffect(() => {
    if (focusOnMount) inputRef.current?.focus();
    // Mount only: later prop changes must not steal focus back.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleInputKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    // During IME composition, Enter confirms the candidate and Backspace
    // edits the composition. Neither may add or arm tags.
    if (event.nativeEvent.isComposing) return;

    onInputKeyDown?.(event);
    if (event.defaultPrevented) return;

    if (event.key === "Enter") {
      // Never submit an enclosing form.
      event.preventDefault();
      event.stopPropagation();
      const trimmed = value.trim();
      if (trimmed) onEnter?.(trimmed);
      return;
    }
    if (event.key === "Backspace" && value === "" && tags.length > 0) {
      event.preventDefault();
      const removes = ownRootRef.current?.querySelectorAll<HTMLButtonElement>(
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
      ref={setRootRef}
      role="presentation"
      className="opal-input opal-input-type-in-tag"
      data-variant={disabled ? "disabled" : variant}
      onKeyDown={handleRootKeyDown}
      onClick={() => inputRef.current?.focus()}
    >
      {Icon && (
        <div className="opal-input-type-in-tag-icon-container">
          <Icon className="opal-input-type-in-tag-icon" />
        </div>
      )}
      <div
        className="opal-input-type-in-tag-tags"
        data-multi-row={minRows > 1 || undefined}
        style={
          minRows > 1
            ? ({
                "--opal-input-type-in-tag-rows": minRows,
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
          // dir="auto": typed text decides the direction, as in InputTypeIn.
          dir="auto"
          className="opal-input-field opal-input-type-in-tag-field"
          disabled={disabled}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onFocus={onInputFocus}
          onClick={onInputClick}
          onKeyDown={handleInputKeyDown}
          placeholder={placeholder}
          aria-label={placeholder}
          {...inputAriaProps}
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
      {children}
    </div>
  );
}

export { TagField, type TagFieldBaseProps, type TagFieldProps, type TagItem };
