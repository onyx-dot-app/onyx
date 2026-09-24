"use client";

import { useCallback, useEffect, useId, useMemo, useRef } from "react";
import {
  TagField,
  type TagItem,
} from "@opal/components/inputs/texts/input-type-in-tag/TagField";
import type { InputTypeInTagProps } from "@opal/components/inputs/texts/input-type-in-tag/components";
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

interface InputMultiSelectProps extends InputTypeInTagProps {
  /**
   * The selectable set. Flat or sectioned — sections render with a Divider
   * between them. Convention: a chosen option becomes a tag whose `id` is
   * the option's `value`, so the dropdown can show it selected and toggle
   * it off.
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
}

// ---------------------------------------------------------------------------
// InputMultiSelect
// ---------------------------------------------------------------------------

/**
 * The multi-arity member of the input-select family: `InputTypeInTag`'s
 * chips-in-input chrome over the family's unified dropdown. Typing filters
 * the option set; chosen options render as Tags. Free tagging with no set
 * to pick from is `InputTypeInTag` itself.
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
  icon,
  onClear,
  minRows,
  focusOnMount,
  dropdownMaxHeight,
}: InputMultiSelectProps) {
  const {
    isOpen,
    setIsOpen,
    highlightedIndex,
    setHighlightedIndex,
    isKeyboardNav,
    setIsKeyboardNav,
    setRootRef,
    inputRef,
    dropdownRef,
    setFloatingRef,
    floatingStyles,
  } = useSelectOverlay();

  const sections = useMemo(() => normalizeSections(optionsProp), [optionsProp]);
  const flatOptions = useMemo(() => flattenSections(sections), [sections]);
  const freeEntry = mode === "open";

  const selectedValues = useMemo(
    () => new Set(tags.map((tag) => tag.id)),
    [tags]
  );

  // Free-form tags (open mode, outside the set) appear in the dropdown as
  // real, selected rows — the single's `customSelected` — so re-picking one
  // routes through the toggle-off instead of the create row.
  const customSelected = useMemo<SelectOption[]>(() => {
    if (!freeEntry) return [];
    const optionValues = new Set(flatOptions.map((option) => option.value));
    return tags
      .filter((tag) => !optionValues.has(tag.id))
      .map((tag) => ({ value: tag.id, label: tag.label }));
  }, [freeEntry, flatOptions, tags]);

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
    ) ||
    tags.some(
      (tag) =>
        tag.id.toLowerCase() === trimmedValue ||
        tag.label.toLowerCase() === trimmedValue
    );
  const showCreateOption = freeEntry && hasSearchTerm && !exactOptionMatch;

  const allVisibleOptions = useMemo(() => {
    const baseOptions = flattenSections(visibleSections);
    if (showCreateOption) {
      // Trimmed, like the create row's own element id, so the keyboard's
      // aria-activedescendant resolves.
      const trimmed = value.trim();
      return [{ value: trimmed, label: trimmed }, ...baseOptions];
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
          onSelectOption(real);
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

  // Enter belongs to the dropdown: the create row covers free-form commits,
  // so the field's own Enter never fires here.
  const { handleKeyDown: handleDropdownKeyDown } = useSelectKeyboard({
    isOpen,
    setIsOpen,
    highlightedIndex,
    setHighlightedIndex,
    setIsKeyboardNav,
    allVisibleOptions,
    onSelect: handleOptionSelect,
  });

  const autoId = useId();
  const fieldId = `multi-select-${autoId}`;
  const ariaProps = {
    ...buildAriaAttributes({
      isOpen,
      isValid: !hasInvalidTag,
      highlightedIndex,
      fieldId,
      allVisibleOptions,
      placeholder: placeholder ?? "",
    }),
    // The multi has no error message element to describe, unlike the single.
    "aria-describedby": undefined,
  };

  return (
    <TagField
      tags={tags}
      onRemoveTag={onRemoveTag}
      value={value}
      onChange={(next) => {
        onChange(next);
        if (!isOpen) setIsOpen(true);
        // No filter, no implicit pick: Enter on an empty input must not
        // commit the first row.
        setHighlightedIndex(next.trim() === "" ? -1 : 0);
        setIsKeyboardNav(false);
      }}
      placeholder={placeholder}
      variant={hasInvalidTag ? "error" : variant}
      disabled={disabled}
      icon={icon}
      onClear={onClear}
      minRows={minRows}
      focusOnMount={focusOnMount}
      rootRef={setRootRef}
      inputRef={inputRef}
      onInputKeyDown={handleDropdownKeyDown}
      onInputFocus={() => setIsOpen(true)}
      // A click on the already-focused input reopens after Escape, like
      // the single's.
      onInputClick={() => setIsOpen(true)}
      inputAriaProps={ariaProps}
    >
      <SelectChevron
        isOpen={isOpen}
        disabled={disabled}
        onToggle={() => {
          setIsOpen((prev) => !prev);
          inputRef.current?.focus();
        }}
      />

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
    </TagField>
  );
}

export { InputMultiSelect, type InputMultiSelectProps, type TagItem };
