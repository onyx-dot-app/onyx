"use client";

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { useOpalStrings } from "@opal/strings";
import {
  TagField,
  type TagItem,
} from "@opal/components/inputs/texts/input-type-in-tag/TagField";
import {
  filterSections,
  flattenSections,
  normalizeSections,
  useSelectKeyboard,
  useSelectOverlay,
  useFoldedGroups,
} from "../shared";
import { SelectDropdown } from "../dropdown/SelectDropdown";
import { SelectChevron } from "../dropdown/SelectChevron";
import { buildAriaAttributes } from "../dropdown/aria";
import type { MultiDropdownProps, SelectOption } from "../types";

// ---------------------------------------------------------------------------
// MultiDropdown
// ---------------------------------------------------------------------------

/**
 * MultiDropdown — the multi-arity implementation behind the family's two
 * public components. Internal to Opal; app code uses `InputMultiSelect`
 * (button trigger) or `InputMultiComboBox` (type-in trigger).
 *
 * `InputTypeInTag`'s chips-in-input chrome over the family's unified
 * dropdown. Chosen options render as Tags. With a `"type-in"` trigger typing
 * filters the option set; with a `"button"` trigger there is no text input
 * and the chips are the whole field. Free tagging with no set to pick from
 * is `InputTypeInTag` itself.
 */
function MultiDropdown(props: MultiDropdownProps) {
  const {
    tags,
    onRemoveTag,
    options: optionsProp,
    onSelectOption,
    placeholder,
    variant = "primary",
    disabled = false,
    icon,
    onClear,
    minRows,
    maxRows,
    focusOnMount,
    dropdownMaxHeight,
  } = props;
  const strings = useOpalStrings();
  const typeIn = props.trigger !== "button";
  const search = props.trigger === "button" && (props.search ?? false);
  // A button trigger has no text: an empty filter, and nothing to commit.
  const value = props.value ?? "";
  const onChange = props.onChange;
  const onAdd = props.onAdd;
  const mode = props.mode ?? "closed";

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

  // A button trigger has no input: its combobox element takes the focus.
  const triggerRef = useRef<HTMLDivElement>(null);
  const focusField = useCallback(() => {
    (typeIn ? inputRef.current : triggerRef.current)?.focus();
  }, [typeIn, inputRef]);

  const sections = useMemo(() => normalizeSections(optionsProp), [optionsProp]);
  const flatOptions = useMemo(() => flattenSections(sections), [sections]);
  const freeEntry = typeIn && mode === "open";

  const selectedValues = useMemo(
    () => new Set(tags.map((tag) => tag.id)),
    [tags]
  );

  // A chip shows its option's icon (by the tag id = option value
  // convention) unless the caller set one on the tag itself.
  const iconTags = useMemo<TagItem[]>(() => {
    const iconByValue = new Map(
      flatOptions.map((option) => [option.value, option.icon])
    );
    return tags.map((tag) =>
      tag.icon ? tag : { ...tag, icon: iconByValue.get(tag.id) }
    );
  }, [tags, flatOptions]);

  // Free-form tags (open mode, outside the set) appear in the dropdown as
  // real, selected rows — the single's `customSelected` — so re-picking one
  // routes through the toggle-off instead of the create row.
  const customSelected = useMemo<SelectOption[]>(() => {
    if (!freeEntry) return [];
    const optionValues = new Set(flatOptions.map((option) => option.value));
    return tags
      .filter((tag) => !optionValues.has(tag.id))
      .map((tag) => ({ value: tag.id, title: tag.label }));
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
    if (typeIn && wasOpenRef.current && !isOpen && value !== "") onChange?.("");
    wasOpenRef.current = isOpen;
  }, [typeIn, isOpen, value, onChange]);

  // A Select with a search field filters through it instead of
  // the typed text; it is transient and clears with the list.
  const [searchText, setSearchText] = useState("");
  useEffect(() => {
    if (!isOpen) setSearchText("");
  }, [isOpen]);
  const filterText = typeIn ? value : search ? searchText : "";
  const hasSearchTerm = filterText.trim() !== "";
  const visibleSections = useMemo(
    () => [
      ...filterSections([{ options: customSelected }], filterText),
      ...filterSections(sections, filterText),
    ],
    [customSelected, sections, filterText]
  );
  const trimmedValue = value.trim().toLowerCase();
  // An exact match means Enter should pick the option — or nothing, when
  // the text already exists as a chip — never fork a duplicate.
  const exactOptionMatch =
    flatOptions.some(
      (option) =>
        option.value.toLowerCase() === trimmedValue ||
        option.title.toLowerCase() === trimmedValue
    ) ||
    tags.some(
      (tag) =>
        tag.id.toLowerCase() === trimmedValue ||
        tag.label.toLowerCase() === trimmedValue
    );
  const showCreateOption = freeEntry && hasSearchTerm && !exactOptionMatch;

  const isSelectedOption = useCallback(
    (option: SelectOption) => selectedValues.has(option.value),
    [selectedValues]
  );
  const { foldedSections, toggleGroup } = useFoldedGroups({
    isOpen,
    sections: visibleSections,
    isSelected: isSelectedOption,
    searching: hasSearchTerm,
  });
  const allVisibleOptions = useMemo(() => {
    const baseOptions = flattenSections(foldedSections);
    if (showCreateOption) {
      // Trimmed, like the create row's own element id, so the keyboard's
      // aria-activedescendant resolves.
      const trimmed = value.trim();
      return [{ value: trimmed, title: trimmed }, ...baseOptions];
    }
    return baseOptions;
  }, [foldedSections, showCreateOption, value]);

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
        if (trimmed) onAdd?.(trimmed);
      }
      // Stay open for further picks; reset the filter.
      onChange?.("");
      focusField();
    },
    [
      flatOptions,
      selectedValues,
      onRemoveTag,
      onSelectOption,
      onAdd,
      onChange,
      focusField,
    ]
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
      typeIn,
    }),
    // The multi has no error message element to describe, unlike the single.
    "aria-describedby": undefined,
  };

  return (
    <TagField
      tags={iconTags}
      onRemoveTag={onRemoveTag}
      readOnly={!typeIn}
      triggerRef={triggerRef}
      value={value}
      onChange={(next) => {
        onChange?.(next);
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
      maxRows={maxRows}
      focusOnMount={focusOnMount}
      rootRef={setRootRef}
      inputRef={inputRef}
      onInputKeyDown={handleDropdownKeyDown}
      // Type-in opens on focus, and a click on the already-focused input
      // reopens after Escape, like the single's. A button trigger opens on
      // click or ArrowDown and a second click closes it; focus alone does
      // not open it.
      onInputFocus={typeIn ? () => setIsOpen(true) : undefined}
      onInputClick={() => setIsOpen((prev) => (typeIn ? true : !prev))}
      inputAriaProps={ariaProps}
    >
      <SelectChevron
        isOpen={isOpen}
        disabled={disabled}
        onToggle={() => {
          setIsOpen((prev) => !prev);
          focusField();
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
        sections={foldedSections}
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
        inputValue={filterText}
        allowCreate={freeEntry}
        showCreateOption={showCreateOption}
        dropdownMaxHeight={dropdownMaxHeight}
        keyboardNav={isKeyboardNav}
        onToggleGroup={toggleGroup}
        searchField={
          search
            ? {
                value: searchText,
                onChange: (next) => {
                  setSearchText(next);
                  setHighlightedIndex(next.trim() ? 0 : -1);
                  setIsKeyboardNav(false);
                },
                onKeyDown: (event) => {
                  handleDropdownKeyDown(event);
                  if (event.key === "Escape" || event.key === "Tab") {
                    focusField();
                  }
                },
                placeholder: strings.selectSearchPlaceholder,
              }
            : undefined
        }
      />
    </TagField>
  );
}

export { MultiDropdown, type TagItem };
