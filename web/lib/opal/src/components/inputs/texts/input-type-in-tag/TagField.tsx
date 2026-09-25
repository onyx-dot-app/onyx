"use client";

import "@opal/components/inputs/shared.css";
// The inner field reuses InputTypeIn's .opal-input-field styling.
import "@opal/components/inputs/texts/input-type-in/styles.css";
import "@opal/components/inputs/texts/input-type-in-tag/styles.css";
import { useCallback, useEffect, useRef } from "react";
import type { IconFunctionComponent } from "@opal/types";
import { Button, Tag, TAG_REMOVE_CLASS, Text } from "@opal/components";
import { SvgX } from "@opal/icons";
import { useOpalStrings } from "@opal/strings";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TagItem {
  id: string;
  label: string;

  /** Leading icon on the tag. */
  icon?: IconFunctionComponent;

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

  /**
   * Tag rows the field grows to before the chips scroll inside it. The
   * text input (or the button trigger) is the last row, so a new chip
   * scrolls it into view.
   */
  maxRows?: number;

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
   * `preventDefault` claims the key. Read-only, it receives the wrapper's
   * own key events instead.
   */
  onInputKeyDown?: (event: React.KeyboardEvent<HTMLElement>) => void;

  /** Enter with non-empty trimmed text, unless `onInputKeyDown` claimed it. */
  onEnter?: (trimmed: string) => void;

  onInputFocus?: () => void;

  onInputClick?: () => void;

  /** Extra attributes on the text input (a select's combobox aria). */
  inputAriaProps?: React.AriaAttributes & { role?: React.AriaRole };

  /** Trailing controls after the clear button (a select's chevron and dropdown). */
  children?: React.ReactNode;

  /**
   * No text input: the chips are the whole field (a select's button
   * trigger). A focusable combobox element takes the aria and the key
   * events the input would have, and shows `placeholder` while there are
   * no tags. Chips stay removable.
   */
  readOnly?: boolean;

  /** The read-only trigger element, when the caller must focus it. */
  triggerRef?: React.RefObject<HTMLDivElement | null>;
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
  maxRows = 2,
  focusOnMount = false,
  rootRef,
  inputRef: inputRefProp,
  onInputKeyDown,
  onEnter,
  onInputFocus,
  onInputClick,
  inputAriaProps,
  children,
  readOnly = false,
  triggerRef: triggerRefProp,
}: TagFieldProps) {
  const strings = useOpalStrings();
  const ownRootRef = useRef<HTMLDivElement>(null);
  const ownInputRef = useRef<HTMLInputElement>(null);
  const ownTriggerRef = useRef<HTMLDivElement>(null);
  const tagsRef = useRef<HTMLDivElement>(null);
  const inputRef = inputRefProp ?? ownInputRef;
  const triggerRef = triggerRefProp ?? ownTriggerRef;

  // Read-only, the combobox element is the focusable field. Disabled, a
  // click must not move focus into the field.
  const focusField = useCallback(() => {
    if (disabled) return;
    (readOnly ? triggerRef.current : inputRef.current)?.focus();
  }, [disabled, readOnly, triggerRef, inputRef]);

  const setRootRef = useCallback(
    (node: HTMLDivElement | null) => {
      ownRootRef.current = node;
      rootRef?.(node);
    },
    [rootRef]
  );

  useEffect(() => {
    if (focusOnMount) focusField();
    // Mount only: later prop changes must not steal focus back.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A new chip lands on the last row, next to the input or the trigger.
  // Past `maxRows` that row is below the fold, so follow it. Removals keep
  // the scroll position: the chip the user is looking at must not move.
  const prevTagCount = useRef(tags.length);
  useEffect(() => {
    const grew = tags.length > prevTagCount.current;
    prevTagCount.current = tags.length;
    const tagsElement = tagsRef.current;
    if (!grew || !tagsElement) return;
    tagsElement.scrollTop = tagsElement.scrollHeight;
  }, [tags.length]);

  // The chips' remove buttons, in order.
  function removeButtons(): HTMLButtonElement[] {
    return Array.from(
      ownRootRef.current?.querySelectorAll<HTMLButtonElement>(
        `.${TAG_REMOVE_CLASS}`
      ) ?? []
    );
  }

  // Backspace with nothing to delete in the field arms the last chip: its
  // remove button takes focus, so the next Backspace removes it.
  function armLastTag(event: React.KeyboardEvent<HTMLElement>) {
    if (event.key !== "Backspace" || tags.length === 0) return;
    event.preventDefault();
    removeButtons().at(-1)?.focus();
  }

  // The button trigger has no text: Backspace arms the last chip directly.
  function handleTriggerKeyDown(event: React.KeyboardEvent<HTMLElement>) {
    onInputKeyDown?.(event);
    if (event.defaultPrevented) return;
    armLastTag(event);
  }

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
    if (value === "") armLastTag(event);
  }

  // Backspace/Delete on an armed remove button deletes its tag. Enter and
  // Space already work as native button activation.
  // Removing from the keyboard then arms the chip before the removed one,
  // so holding Backspace clears chips one by one; with none left, focus
  // returns to the field.
  function handleRootKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Backspace" && event.key !== "Delete") return;
    const target = event.target as HTMLElement;
    if (!target.classList.contains(TAG_REMOVE_CLASS)) return;
    event.preventDefault();
    const index = removeButtons().indexOf(target as HTMLButtonElement);
    target.click();
    requestAnimationFrame(() => {
      const previous = index > 0 ? removeButtons()[index - 1] : undefined;
      if (previous) previous.focus();
      else focusField();
    });
  }

  return (
    <div
      ref={setRootRef}
      role="presentation"
      className="opal-input opal-input-type-in-tag"
      data-variant={disabled ? "disabled" : variant}
      data-read-only={readOnly || undefined}
      onKeyDown={handleRootKeyDown}
      onClick={focusField}
    >
      {Icon && (
        <div className="opal-input-type-in-tag-icon-container">
          <Icon className="opal-input-type-in-tag-icon" />
        </div>
      )}
      <div
        ref={tagsRef}
        className="opal-input-type-in-tag-tags"
        style={
          {
            "--opal-input-type-in-tag-rows": minRows,
            "--opal-input-type-in-tag-max-rows": Math.max(maxRows, minRows),
          } as React.CSSProperties
        }
      >
        {tags.map((tag) => (
          <Tag
            key={tag.id}
            size="md"
            title={tag.label}
            icon={tag.icon}
            error={tag.error}
            disabled={disabled}
            onRemove={() => {
              onRemoveTag(tag.id);
              focusField();
            }}
          />
        ))}
        {readOnly ? (
          <div
            ref={triggerRef}
            role="combobox"
            tabIndex={disabled ? -1 : 0}
            className="opal-input-type-in-tag-trigger"
            aria-label={placeholder}
            {...inputAriaProps}
            // Named here as well as in the spread: the combobox role
            // requires them, and the caller's spread is opaque to lint.
            aria-expanded={inputAriaProps?.["aria-expanded"] ?? false}
            aria-controls={inputAriaProps?.["aria-controls"]}
            aria-disabled={disabled || undefined}
            onFocus={disabled ? undefined : onInputFocus}
            onClick={disabled ? undefined : onInputClick}
            onKeyDown={disabled ? undefined : handleTriggerKeyDown}
          >
            {tags.length === 0 && placeholder && (
              <Text font="main-ui-muted" color="text-02">
                {placeholder}
              </Text>
            )}
          </div>
        ) : (
          /* raw-ok: nesting InputTypeIn double-pads the composite chrome, so the inner field reuses InputTypeIn's .opal-input-field styling directly */
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
        )}
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
