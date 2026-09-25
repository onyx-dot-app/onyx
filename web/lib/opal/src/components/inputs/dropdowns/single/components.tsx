"use client";

/**
 * SingleDropdown — the single-arity implementation behind the family's two
 * public components. Internal to Opal; app code uses `InputSingleSelect`
 * (button trigger) or `InputSingleComboBox` (type-in trigger).
 *
 * An input-shaped trigger over the family's unified dropdown: keyboard
 * navigation and selection live in the shared hooks, and sections render
 * with a Divider between them.
 *
 * - `trigger="type-in"` (ComboBox): typing filters the option set.
 *   `mode="closed"` permits only option values; `mode="open"` also commits
 *   the raw text via the create row.
 * - `trigger="button"` (Select): nothing to type. A click or ArrowDown opens
 *   the full set, a second click closes it, and focus alone does not.
 *
 * Re-picking the selected option unselects it. A Select may carry a
 * `defaultOption`, and then never reads as empty: an empty value resolves to
 * it and re-picking any option is a no-op, like a native `<select>`. A
 * ComboBox takes none: its text is the filter, and a default would pre-fill
 * it with a label the user never chose. Either way `placeholder` names the
 * field for assistive technology.
 *
 * With no options a ComboBox degrades to a plain input.
 */

import "@opal/components/inputs/dropdowns/single/styles.css";
import React, {
  useCallback,
  useContext,
  useMemo,
  useState,
  useId,
  useEffect,
} from "react";
import { useOpalStrings } from "@opal/strings";
import { cn, noProp } from "@opal/utils";
import { InputTypeIn } from "@opal/components";
import { FieldContext } from "@opal/form";
import { Button } from "@opal/components";
import { FieldMessage } from "@opal/form";

// Hooks
import {
  useFoldedGroups,
  useSelectKeyboard,
  useSelectOverlay,
  filterSections,
  flattenSections,
  normalizeSections,
} from "../shared";
import { useValidation } from "./validation";
import { buildAriaAttributes } from "../dropdown/aria";

// Components
import { SelectDropdown } from "../dropdown/SelectDropdown";
import { SelectChevron } from "../dropdown/SelectChevron";

// Types
import type { SelectOption, SingleDropdownProps } from "../types";
import { ChevronIcon } from "@opal/components/buttons/chevron";
import type { WithoutStyles } from "@opal/types";

function SingleDropdown({
  value,
  onChange,
  onValueChange,
  options: optionsProp,
  trigger,
  mode = "closed",
  defaultOption,
  disabled = false,
  placeholder,
  isError: externalIsError,
  onValidationError,
  name,
  searchIcon = false,
  rightChildren,
  separatorLabel,
  showOtherOptions = false,
  dropdownMaxHeight,
  search = false,
  ...rest
}: WithoutStyles<SingleDropdownProps>) {
  const typeIn = trigger === "type-in";
  // A button trigger has no text to commit, so its set is always closed.
  const strict = !typeIn || mode !== "open";
  const sections = useMemo(() => normalizeSections(optionsProp), [optionsProp]);
  const options = useMemo(() => flattenSections(sections), [sections]);
  // The value the trigger shows and the dropdown marks: `defaultOption`
  // stands in for an empty value, so the select never reads as empty.
  const effectiveValue = value || defaultOption || "";
  const strings = useOpalStrings();
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
  const fieldContext = useContext(FieldContext);

  // The selection's visible text — the ONLY value-to-text crossing point.
  // A strict set shows nothing for a value outside it (the placeholder, with
  // the validation error); only an open set displays a free-form value.
  const selectedOption = useMemo(
    () => options.find((opt) => opt.value === effectiveValue),
    [options, effectiveValue]
  );
  const selectedLabel = useMemo(() => {
    if (!effectiveValue) return "";
    return selectedOption?.title ?? (strict ? "" : effectiveValue);
  }, [selectedOption, effectiveValue, strict]);

  useEffect(() => {
    if (
      process.env.NODE_ENV !== "production" &&
      defaultOption !== undefined &&
      options.length > 0 &&
      !options.some((opt) => opt.value === defaultOption)
    ) {
      console.warn(
        `InputSingleSelect: defaultOption "${defaultOption}" is not in the option set.`
      );
    }
  }, [defaultOption, options]);

  // Trigger text is ALWAYS display text (a label or the user's filter);
  // `value` is the only value-typed state. Closed, the text mirrors the
  // selection's label; open, only a value-prop change may overwrite it.
  const [inputValue, setInputValue] = useState(selectedLabel);
  useEffect(() => {
    if (!isOpen) setInputValue(selectedLabel);
  }, [selectedLabel, isOpen]);
  useEffect(() => {
    if (isOpen && options.some((opt) => opt.value === effectiveValue)) {
      setInputValue(selectedLabel);
    }
    // Only react to value prop changes while open, not inputValue changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  // A committed free-form value (open mode, outside the set) appears in the
  // dropdown as a real, selected row — not as a create-row impostor — and
  // re-picking it routes through the toggle-off.
  const customSelected = useMemo(() => {
    if (strict || !effectiveValue) return null;
    if (options.some((opt) => opt.value === effectiveValue)) return null;
    return { value: effectiveValue, title: effectiveValue };
  }, [strict, effectiveValue, options]);

  // What filters the list: a ComboBox's typed text, or a Select's search
  // field when it has one. Otherwise nothing: a button trigger's text is
  // only ever the selection's label. The search is transient and clears
  // with the list.
  const [searchText, setSearchText] = useState("");
  useEffect(() => {
    if (!isOpen) setSearchText("");
  }, [isOpen]);
  const filterText = typeIn ? inputValue : search ? searchText : "";

  // Filtering: each section filters independently; empty ones disappear.
  const hasSearchTerm = filterText.trim() !== "";
  const visibleSections = useMemo(() => {
    const customSection =
      customSelected &&
      (!hasSearchTerm ||
        customSelected.title
          .toLowerCase()
          .includes(filterText.trim().toLowerCase()))
        ? [{ options: [customSelected] }]
        : [];
    const filtered = [
      ...customSection,
      ...filterSections(sections, filterText),
    ];
    if (hasSearchTerm && showOtherOptions) {
      const visibleIds = new Set(
        flattenSections(filtered).map((option) => option.value)
      );
      const unmatched = options.filter(
        (option) => !visibleIds.has(option.value)
      );
      if (unmatched.length > 0) {
        return [
          ...filtered,
          {
            title: separatorLabel ?? strings.comboBoxOtherOptions,
            options: unmatched,
          },
        ];
      }
    }
    return filtered;
  }, [
    customSelected,
    sections,
    filterText,
    hasSearchTerm,
    showOtherOptions,
    options,
    separatorLabel,
    strings,
  ]);

  // The create row offers what ISN'T already offerable: it hides when the
  // text exactly matches an option or the committed free-form value.
  const trimmedInput = filterText.trim().toLowerCase();
  const exactVisibleMatch = useMemo(() => {
    const candidates = customSelected ? [customSelected, ...options] : options;
    return candidates.some(
      (opt) =>
        opt.value.toLowerCase() === trimmedInput ||
        opt.title.toLowerCase() === trimmedInput
    );
  }, [customSelected, options, trimmedInput]);
  const showCreateOption = !strict && hasSearchTerm && !exactVisibleMatch;

  // Foldable groups withhold their rows while folded, for rendering and
  // for the keyboard order alike.
  const isSelectedOption = useCallback(
    (option: SelectOption) => option.value === effectiveValue,
    [effectiveValue]
  );
  const { foldedSections, toggleGroup } = useFoldedGroups({
    isOpen,
    sections: visibleSections,
    isSelected: isSelectedOption,
    searching: hasSearchTerm,
  });

  // Combined list for keyboard navigation (includes create option when shown)
  // Only show matched options when searching (hide unmatched)
  const allVisibleOptions = useMemo(() => {
    const baseOptions = flattenSections(foldedSections);
    if (showCreateOption) {
      // Prepend a synthetic option for the "create new" item. Trimmed to
      // match what the rendered create row commits.
      const createText = filterText.trim();
      return [{ value: createText, title: createText }, ...baseOptions];
    }
    return baseOptions;
  }, [foldedSections, showCreateOption, filterText]);

  // Check if an option is an exact match
  const isExactMatch = useCallback(
    (option: SelectOption) => {
      const currentValue = (filterText || effectiveValue || "")
        .trim()
        .toLowerCase();
      if (!currentValue) return false;

      return (
        option.value.toLowerCase() === currentValue ||
        option.title.toLowerCase() === currentValue
      );
    },
    [filterText, effectiveValue]
  );

  // Validation Logic
  const { isValid, errorMessage } = useValidation({
    value: effectiveValue,
    options,
    strict,
    externalIsError,
    onValidationError,
  });

  // Sync highlightedIndex with exact match when typing (not keyboard nav)
  useEffect(() => {
    // Skip if keyboard navigating or dropdown closed
    if (isKeyboardNav || !isOpen) return;
    if (!filterText.trim()) return;

    const exactMatchIndex = allVisibleOptions.findIndex(
      (opt) =>
        opt.value.toLowerCase() === filterText.trim().toLowerCase() ||
        opt.title.toLowerCase() === filterText.trim().toLowerCase()
    );

    if (exactMatchIndex >= 0) {
      setHighlightedIndex(exactMatchIndex);
    }
  }, [
    filterText,
    allVisibleOptions,
    isKeyboardNav,
    isOpen,
    setHighlightedIndex,
  ]);

  // Event Handlers
  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const newValue = e.target.value;
      setInputValue(newValue);
      setInvalidCommit(false);

      // Only call onChange while typing (for controlled input behavior)
      // onValueChange is only called when selecting from dropdown
      onChange?.(e);

      // Open dropdown when user starts typing
      if (!isOpen) {
        setIsOpen(true);
      }

      // Auto-highlight first match when typing
      setHighlightedIndex(0);
      setIsKeyboardNav(false); // Reset keyboard navigation mode when typing
    },
    [
      onChange,
      isOpen,
      setInputValue,
      setIsOpen,
      setHighlightedIndex,
      setIsKeyboardNav,
    ]
  );

  // Support both onChange (event) and onValueChange (value) patterns
  const emitValue = useCallback(
    (next: string) => {
      if (onChange) {
        const syntheticEvent = {
          target: { value: next },
          currentTarget: { value: next },
          type: "change",
          bubbles: true,
          cancelable: true,
        } as React.ChangeEvent<HTMLInputElement>;
        onChange(syntheticEvent);
      }
      onValueChange?.(next);
    },
    [onChange, onValueChange]
  );

  const handleOptionSelect = useCallback(
    (option: SelectOption) => {
      if (option.disabled) return;

      // Re-picking is judged against the committed value, not the displayed
      // one: picking a default that only stands in for an empty value must
      // commit it. Re-picking the committed option then has the multi's
      // symmetry: it unselects, and the dropdown stays open with the filter
      // cleared, ready for a different pick. With a default there is nothing
      // to unselect into, so a re-pick just closes the list, like a native
      // <select>. Both triggers behave the same.
      if (option.value === value && value !== "") {
        if (defaultOption !== undefined) {
          setIsOpen(false);
          inputRef.current?.focus();
          return;
        }
        setInputValue("");
        emitValue("");
        setHighlightedIndex(-1);
        inputRef.current?.focus();
        return;
      }

      setInputValue(option.title);
      emitValue(option.value);
      setIsOpen(false);
      inputRef.current?.focus();
    },
    [
      value,
      defaultOption,
      options,
      emitValue,
      setInputValue,
      setIsOpen,
      setHighlightedIndex,
    ]
  );

  // Keyboard Navigation Hook
  // EXPERIMENT(commit-attempt errors): Enter on text matching no option in
  // closed mode flags the error variant and keeps the dropdown open; any
  // typing, selection, or close (blur/outside/Tab already close) clears it,
  // and the close-sync effect drops the invalid text back to the selection.
  const [invalidCommit, setInvalidCommit] = useState(false);
  useEffect(() => {
    if (!isOpen) setInvalidCommit(false);
  }, [isOpen]);

  const { handleKeyDown } = useSelectKeyboard({
    isOpen,
    setIsOpen,
    highlightedIndex,
    setHighlightedIndex,
    setIsKeyboardNav,
    allVisibleOptions,
    onSelect: handleOptionSelect,
  });

  const handleFocus = useCallback(() => {
    setInputValue(selectedLabel);
    setIsOpen(true);
    setHighlightedIndex(-1);
    setIsKeyboardNav(false);
    // Caret at the end, ready to modify.
    requestAnimationFrame(() => {
      const el = inputRef.current;
      if (el) el.setSelectionRange(el.value.length, el.value.length);
    });
  }, [
    selectedLabel,
    setInputValue,
    setIsOpen,
    setHighlightedIndex,
    setIsKeyboardNav,
  ]);

  const toggleDropdown = useCallback(() => {
    if (disabled) return;
    setIsOpen((prev) => {
      const newOpen = !prev;
      if (newOpen) {
        // Type-in clears the filter to show the whole set; a button trigger has
        // no filter and keeps the selection's label.
        if (typeIn) setInputValue("");
        setHighlightedIndex(-1);
      }
      return newOpen;
    });
    inputRef.current?.focus();
  }, [disabled, typeIn, setIsOpen, setInputValue, setHighlightedIndex]);

  const autoId = useId();
  const fieldId = fieldContext?.baseId || name || `combo-box-${autoId}`;

  // ARIA Attributes Builder
  const ariaProps = buildAriaAttributes({
    isOpen,
    isValid,
    highlightedIndex,
    fieldId,
    allVisibleOptions,
    placeholder,
    typeIn,
  });

  return (
    <div
      ref={setRootRef}
      role="presentation"
      className="opal-input-single-select"
      data-trigger={trigger}
      // A button trigger is the whole field, padding included, so the
      // toggle lives on the root; the input inside carries the keyboard,
      // and the chevron and rightChildren stop propagation.
      onClick={typeIn ? undefined : toggleDropdown}
    >
      <>
        <InputTypeIn
          ref={inputRef}
          name={name}
          placeholder={placeholder}
          readOnly={!typeIn}
          // A Select shows the chosen option's icon; a ComboBox's text is
          // typed, so it shows none.
          icon={typeIn ? undefined : selectedOption?.icon}
          value={inputValue}
          onChange={handleInputChange}
          // A button trigger opens on click or ArrowDown and a second click
          // closes it, like a native <select>; keyboard focus alone does
          // not open it. Type-in opens on focus, and a click while focused
          // reopens it (e.g. after Escape) with the text kept for editing.
          onFocus={typeIn ? handleFocus : undefined}
          onClick={() => {
            if (!typeIn) return;
            if (!isOpen) {
              setInputValue(selectedLabel);
              setIsOpen(true);
              setHighlightedIndex(-1);
            }
          }}
          onKeyDown={(event) => {
            if (
              typeIn &&
              event.key === "Enter" &&
              strict &&
              isOpen &&
              highlightedIndex < 0 &&
              inputValue.trim() !== ""
            ) {
              // Commit attempt with nothing selectable: reject visibly.
              event.preventDefault();
              event.stopPropagation();
              setInvalidCommit(true);
              return;
            }
            handleKeyDown(event);
          }}
          variant={
            disabled
              ? "disabled"
              : !isValid || invalidCommit
                ? "error"
                : undefined
          }
          searchIcon={searchIcon}
          rightChildren={
            <>
              {rightChildren && (
                // Propagation guard only — the children keep their own
                // semantics.
                <div
                  role="presentation"
                  className="flex items-center"
                  onPointerDown={(e) => {
                    e.stopPropagation();
                  }}
                  onClick={(e) => {
                    e.stopPropagation();
                  }}
                >
                  {rightChildren}
                </div>
              )}
              <SelectChevron
                isOpen={isOpen}
                disabled={disabled}
                onToggle={toggleDropdown}
              />
            </>
          }
          {...ariaProps}
          {...rest}
        />

        {/* Dropdown - Rendered in Portal */}
        <SelectDropdown
          ref={dropdownRef}
          isOpen={isOpen}
          disabled={disabled}
          floatingStyles={floatingStyles}
          setFloatingRef={setFloatingRef}
          fieldId={fieldId}
          placeholder={placeholder ?? ""}
          sections={foldedSections}
          emptySet={options.length === 0}
          value={effectiveValue}
          highlightedIndex={highlightedIndex}
          onSelect={handleOptionSelect}
          onMouseEnter={(index) => {
            setIsKeyboardNav(false);
            setHighlightedIndex(index);
          }}
          onMouseMove={() => {
            if (isKeyboardNav) {
              setIsKeyboardNav(false);
            }
          }}
          onMouseLeave={() => {
            if (!isKeyboardNav) setHighlightedIndex(-1);
          }}
          isExactMatch={isExactMatch}
          inputValue={filterText}
          allowCreate={!strict}
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
                    handleKeyDown(event);
                    // Escape and Tab close the list; focus goes back to
                    // the trigger so the field is not left orphaned.
                    if (event.key === "Escape" || event.key === "Tab") {
                      inputRef.current?.focus();
                    }
                  },
                  placeholder: strings.selectSearchPlaceholder,
                }
              : undefined
          }
        />
      </>

      {/* Error message - only show internal error messages when not using external isError */}
      {!isValid && errorMessage && externalIsError === undefined && (
        <FieldMessage variant="error" className="ms-0.5 mt-1">
          <FieldMessage.Content
            id={`${fieldId}-error`}
            role="alert"
            className="ms-0.5"
          >
            {errorMessage}
          </FieldMessage.Content>
        </FieldMessage>
      )}
    </div>
  );
}

export { SingleDropdown };
