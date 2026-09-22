"use client";

import "@opal/components/inputs/shared.css";
// The inner field reuses InputTypeIn's .opal-input-field styling.
import "@opal/components/inputs/input-type-in/styles.css";
import "@opal/components/inputs/selections/input-multi-select/styles.css";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import type { IconFunctionComponent } from "@opal/types";
import { Button, Tag, TAG_REMOVE_CLASS } from "@opal/components";
import { SvgX } from "@opal/icons";
import { ChevronIcon } from "@opal/components/buttons/chevron";
import { useOpalStrings } from "@opal/strings";
import {
  filterSections,
  flattenSections,
  normalizeSections,
  useSelectKeyboard,
  useSelectOverlay,
} from "../shared";
import { SelectDropdown } from "../dropdown/SelectDropdown";
import { SelectChevron } from "../dropdown/SelectChevron";
import { buildAriaAttributes } from "../dropdown/aria";
import type { SelectOption, SelectSection } from "../types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TagItem {
  id: string;
  label: string;

  /** Shows the warning indicator on the tag. */
  error?: boolean;
}

/**
 * Supplying `options` requires `onSelectOption`: without a handler a chosen
 * option would vanish (nothing writes it into `tags`), so the pairing is
 * enforced where it can't be forgotten — the types.
 */
type InputMultiSelectOptionsProps =
  | {
      /**
       * Without a set the field is the plain tag input: no dropdown, and
       * Enter commits the typed text through `onAdd`. The dropdown-only
       * props have nothing to configure.
       */
      options?: never;
      onSelectOption?: never;
      mode?: never;
      dropdownMaxHeight?: never;
    }
  | {
      /**
       * The selectable set; enables the family dropdown. Flat or sectioned —
       * sections render with a Divider between them. Convention: a chosen
       * option becomes a tag whose `id` is the option's `value`, so the
       * dropdown can show it selected and toggle it off.
       */
      options: SelectOption[] | SelectSection[];

      /**
       * Called when a dropdown option is chosen. Choosing an already-selected
       * option calls `onRemoveTag(option.value)` instead — one removal path.
       */
      onSelectOption: (option: SelectOption) => void;

      /**
       * Set openness:
       * - "closed" (default): only options can be chosen; typing filters.
       * - "open": typing filters AND the raw text commits via the create row.
       */
      mode?: "closed" | "open";

      /** Max height of the dropdown in CSS units. Defaults to "15rem". */
      dropdownMaxHeight?: string;
    };

interface InputMultiSelectBaseProps {
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

type InputMultiSelectProps = InputMultiSelectBaseProps &
  InputMultiSelectOptionsProps;

// ---------------------------------------------------------------------------
// InputMultiSelect
// ---------------------------------------------------------------------------

/**
 * The multi-arity member of the input-select family: chips-in-input (Figma
 * `Input/Tags`) over the family's unified dropdown. Typing filters the
 * option set; chosen options render as Tags. Backspace on an empty input
 * arms the last tag, and Backspace or Delete on an armed tag removes it.
 *
 * Without `options` it is the plain free-tagging input: no dropdown, and
 * Enter commits the typed text through `onAdd`.
 */
function InputMultiSelect({
  tags,
  onRemoveTag,
  onAdd,
  value,
  onChange,
  options: optionsProp,
  mode = "closed",
  onSelectOption,
  placeholder,
  variant = "primary",
  disabled = false,
  icon: Icon,
  onClear,
  minRows = 1,
  focusOnMount = false,
  dropdownMaxHeight,
}: InputMultiSelectProps) {
  const strings = useOpalStrings();
  const {
    isOpen,
    setIsOpen,
    highlightedIndex,
    setHighlightedIndex,
    isKeyboardNav,
    setIsKeyboardNav,
    rootRef,
    setRootRef,
    inputRef,
    dropdownRef,
    setFloatingRef,
    floatingStyles,
  } = useSelectOverlay();

  const sections = useMemo(
    () => normalizeSections(optionsProp ?? []),
    [optionsProp]
  );
  const flatOptions = useMemo(() => flattenSections(sections), [sections]);
  // No set, no dropdown: the field is plain free tagging. With a set, only
  // "open" mode admits free-form text, via the create row.
  const hasDropdown = optionsProp !== undefined;
  const freeEntry = !hasDropdown || mode === "open";

  const selectedValues = useMemo(
    () => new Set(tags.map((tag) => tag.id)),
    [tags]
  );

  // Free-form tags (open mode, outside the set) appear in the dropdown as
  // real, selected rows — the single's `customSelected` — so re-picking one
  // routes through the toggle-off instead of the create row.
  const customSelected = useMemo<SelectOption[]>(() => {
    if (!hasDropdown || !freeEntry) return [];
    const optionValues = new Set(flatOptions.map((option) => option.value));
    return tags
      .filter((tag) => !optionValues.has(tag.id))
      .map((tag) => ({ value: tag.id, label: tag.label }));
  }, [hasDropdown, freeEntry, flatOptions, tags]);

  // Closed-set doctrine, committed values only: a tag outside the supplied
  // set (stale seed, options shrank) flags the input chrome's error variant.
  // Open mode legitimately holds free-form tags, and typing never flags.
  const hasInvalidTag = useMemo(() => {
    if (freeEntry) return false;
    const optionValues = new Set(flatOptions.map((option) => option.value));
    return tags.some((tag) => !optionValues.has(tag.id));
  }, [freeEntry, flatOptions, tags]);

  // The filter is transient UI state, like the single's: closing the
  // dropdown drops whatever was typed (the caller owns the text, so the
  // component clears it through onChange).
  // Only the open→closed transition acts; other dep changes just no-op.
  const wasOpenRef = useRef(false);
  useEffect(() => {
    if (wasOpenRef.current && !isOpen && value !== "") onChange("");
    wasOpenRef.current = isOpen;
  }, [isOpen, value, onChange]);

  const hasSearchTerm = value.trim() !== "";
  const visibleSections = useMemo(
    () => [
      ...filterSections([{ options: customSelected }], value),
      ...filterSections(sections, value),
    ],
    [customSelected, sections, value]
  );
  const trimmedValue = value.trim().toLowerCase();
  // An exact match means Enter should pick the option — or nothing, when
  // the text already exists as a chip — never fork a duplicate.
  const exactOptionMatch =
    flatOptions.some(
      (option) =>
        option.value.toLowerCase() === trimmedValue ||
        option.label.toLowerCase() === trimmedValue
    ) || tags.some((tag) => tag.label.toLowerCase() === trimmedValue);
  const showCreateOption =
    hasDropdown && freeEntry && hasSearchTerm && !exactOptionMatch;

  const allVisibleOptions = useMemo(() => {
    const baseOptions = flattenSections(visibleSections);
    if (showCreateOption) {
      return [{ value, label: value }, ...baseOptions];
    }
    return baseOptions;
  }, [visibleSections, showCreateOption, value]);

  const handleOptionSelect = useCallback(
    (option: SelectOption) => {
      if (option.disabled) return;
      const real = flatOptions.find((o) => o.value === option.value);
      if (real) {
        if (selectedValues.has(real.value)) {
          onRemoveTag(real.value);
        } else {
          onSelectOption?.(real);
        }
      } else if (selectedValues.has(option.value)) {
        // A free-form tag's own row: toggle it off.
        onRemoveTag(option.value);
      } else {
        // The create row: commit the raw text as a free-form tag.
        const trimmed = option.value.trim();
        if (trimmed) onAdd(trimmed);
      }
      // Stay open for further picks; reset the filter.
      onChange("");
      inputRef.current?.focus();
    },
    [flatOptions, selectedValues, onRemoveTag, onSelectOption, onAdd, onChange]
  );

  const { handleKeyDown: handleDropdownKeyDown } = useSelectKeyboard({
    isOpen,
    setIsOpen,
    highlightedIndex,
    setHighlightedIndex,
    setIsKeyboardNav,
    allVisibleOptions,
    onSelect: handleOptionSelect,
  });

  useEffect(() => {
    if (focusOnMount) inputRef.current?.focus();
    // Mount only: later prop changes must not steal focus back.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleInputKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    // During IME composition, Enter confirms the candidate and Backspace
    // edits the composition. Neither may add or arm tags.
    if (event.nativeEvent.isComposing) return;

    if (hasDropdown) {
      handleDropdownKeyDown(event);
      if (event.defaultPrevented) return;
    }

    if (event.key === "Enter") {
      // Never submit an enclosing form. With a dropdown, Enter belongs to
      // it and the create row covers free-form commits; without one, Enter
      // commits the text directly.
      event.preventDefault();
      event.stopPropagation();
      if (!hasDropdown) {
        const trimmed = value.trim();
        if (trimmed) onAdd(trimmed);
      }
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

  const autoId = useId();
  const fieldId = `multi-select-${autoId}`;
  // Only a field with a dropdown is a combobox; without one it stays a
  // plain textbox.
  const ariaProps = hasDropdown
    ? buildAriaAttributes({
        isOpen,
        isValid: true,
        highlightedIndex,
        fieldId,
        allVisibleOptions,
        placeholder: placeholder ?? "",
      })
    : { "aria-label": placeholder };

  return (
    <div
      ref={setRootRef}
      role="presentation"
      className="opal-input opal-input-multi-select"
      data-variant={disabled ? "disabled" : hasInvalidTag ? "error" : variant}
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
          onChange={(event) => {
            onChange(event.target.value);
            if (!hasDropdown) return;
            if (!isOpen) setIsOpen(true);
            setHighlightedIndex(0);
            setIsKeyboardNav(false);
          }}
          onFocus={() => {
            if (hasDropdown) setIsOpen(true);
          }}
          onKeyDown={handleInputKeyDown}
          placeholder={placeholder}
          {...ariaProps}
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
      {hasDropdown && (
        <SelectChevron
          isOpen={isOpen}
          disabled={disabled}
          onToggle={() => {
            setIsOpen((prev) => !prev);
            inputRef.current?.focus();
          }}
        />
      )}

      {hasDropdown && (
        <SelectDropdown
          ref={dropdownRef}
          isOpen={isOpen}
          disabled={disabled}
          floatingStyles={floatingStyles}
          setFloatingRef={setFloatingRef}
          fieldId={fieldId}
          placeholder={placeholder ?? ""}
          sections={visibleSections}
          emptySet={flatOptions.length === 0}
          value=""
          selectedValues={selectedValues}
          highlightedIndex={highlightedIndex}
          onSelect={handleOptionSelect}
          onMouseEnter={(index) => {
            setIsKeyboardNav(false);
            setHighlightedIndex(index);
          }}
          onMouseMove={() => {
            if (isKeyboardNav) setIsKeyboardNav(false);
          }}
          onMouseLeave={() => {
            if (!isKeyboardNav) setHighlightedIndex(-1);
          }}
          isExactMatch={(option) => selectedValues.has(option.value)}
          markAllMatches
          inputValue={value}
          allowCreate={freeEntry}
          showCreateOption={showCreateOption}
          dropdownMaxHeight={dropdownMaxHeight}
        />
      )}
    </div>
  );
}

export { InputMultiSelect, type InputMultiSelectProps, type TagItem };
