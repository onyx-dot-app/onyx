"use client";

/**
 * InputSingleSelect — the single-arity member of the input-select family.
 *
 * An input-shaped trigger over the family's unified dropdown: typing always
 * filters the option set, keyboard navigation and selection live in the
 * shared hooks, and sections render with a Divider between them.
 *
 * - `mode="closed"` (default): only option values are allowed; the trigger
 *   shows the selected option's label at rest.
 * - `mode="open"`: the raw text can be committed as a value via the create
 *   row (the old InputComboBox non-strict behavior).
 *
 * With no options it degrades to a plain input.
 */

import "@opal/components/inputs/selects/input-single-select/styles.css";
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
import { InputSingleSelectProps, SelectOption } from "../types";
import { ChevronIcon } from "@opal/components/buttons/chevron";
import type { WithoutStyles } from "@opal/types";

const InputSingleSelect = ({
  value,
  onChange,
  onValueChange,
  options: optionsProp,
  mode = "closed",
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
  ...rest
}: WithoutStyles<InputSingleSelectProps>) => {
  const strict = mode !== "open";
  const sections = useMemo(() => normalizeSections(optionsProp), [optionsProp]);
  const options = useMemo(() => flattenSections(sections), [sections]);
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
  const selectedLabel = useMemo(() => {
    if (!value) return "";
    return options.find((opt) => opt.value === value)?.label ?? value;
  }, [options, value]);

  // Trigger text is ALWAYS display text (a label or the user's filter);
  // `value` is the only value-typed state. Closed, the text mirrors the
  // selection's label; open, only a value-prop change may overwrite it.
  const [inputValue, setInputValue] = useState(selectedLabel);
  useEffect(() => {
    if (!isOpen) setInputValue(selectedLabel);
  }, [selectedLabel, isOpen]);
  useEffect(() => {
    if (isOpen && options.some((opt) => opt.value === value)) {
      setInputValue(selectedLabel);
    }
    // Only react to value prop changes while open, not inputValue changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  // A committed free-form value (open mode, outside the set) appears in the
  // dropdown as a real, selected row — not as a create-row impostor — and
  // re-picking it routes through the toggle-off.
  const customSelected = useMemo(() => {
    if (strict || !value) return null;
    if (options.some((opt) => opt.value === value)) return null;
    return { value, label: value };
  }, [strict, value, options]);

  // Filtering: each section filters independently; empty ones disappear.
  const hasSearchTerm = inputValue.trim() !== "";
  const visibleSections = useMemo(() => {
    const customSection =
      customSelected &&
      (!hasSearchTerm ||
        customSelected.label
          .toLowerCase()
          .includes(inputValue.trim().toLowerCase()))
        ? [{ options: [customSelected] }]
        : [];
    const filtered = [
      ...customSection,
      ...filterSections(sections, inputValue),
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
            label: separatorLabel ?? strings.comboBoxOtherOptions,
            options: unmatched,
          },
        ];
      }
    }
    return filtered;
  }, [
    customSelected,
    sections,
    inputValue,
    hasSearchTerm,
    showOtherOptions,
    options,
    separatorLabel,
    strings,
  ]);

  // The create row offers what ISN'T already offerable: it hides when the
  // text exactly matches an option or the committed free-form value.
  const trimmedInput = inputValue.trim().toLowerCase();
  const exactVisibleMatch = useMemo(() => {
    const candidates = customSelected ? [customSelected, ...options] : options;
    return candidates.some(
      (opt) =>
        opt.value.toLowerCase() === trimmedInput ||
        opt.label.toLowerCase() === trimmedInput
    );
  }, [customSelected, options, trimmedInput]);
  const showCreateOption = !strict && hasSearchTerm && !exactVisibleMatch;

  // Combined list for keyboard navigation (includes create option when shown)
  // Only show matched options when searching (hide unmatched)
  const allVisibleOptions = useMemo(() => {
    const baseOptions = flattenSections(visibleSections);
    if (showCreateOption) {
      // Prepend a synthetic option for the "create new" item. Trimmed to
      // match what the rendered create row commits.
      const createText = inputValue.trim();
      return [{ value: createText, label: createText }, ...baseOptions];
    }
    return baseOptions;
  }, [visibleSections, showCreateOption, inputValue]);

  // Check if an option is an exact match
  const isExactMatch = useCallback(
    (option: SelectOption) => {
      const currentValue = (inputValue || value || "").trim().toLowerCase();
      if (!currentValue) return false;

      return (
        option.value.toLowerCase() === currentValue ||
        option.label.toLowerCase() === currentValue
      );
    },
    [inputValue, value]
  );

  // Validation Logic
  const { isValid, errorMessage } = useValidation({
    value,
    options,
    strict,
    externalIsError,
    onValidationError,
  });

  // Sync highlightedIndex with exact match when typing (not keyboard nav)
  useEffect(() => {
    // Skip if keyboard navigating or dropdown closed
    if (isKeyboardNav || !isOpen) return;
    if (!inputValue.trim()) return;

    const exactMatchIndex = allVisibleOptions.findIndex(
      (opt) =>
        opt.value.toLowerCase() === inputValue.trim().toLowerCase() ||
        opt.label.toLowerCase() === inputValue.trim().toLowerCase()
    );

    if (exactMatchIndex >= 0) {
      setHighlightedIndex(exactMatchIndex);
    }
  }, [
    inputValue,
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

      // The multi's symmetry: picking the already-selected option unselects
      // it. The dropdown stays open with the filter cleared, ready for a
      // different pick.
      if (option.value === value && value !== "") {
        setInputValue("");
        emitValue("");
        setHighlightedIndex(-1);
        inputRef.current?.focus();
        return;
      }

      setInputValue(option.label);
      emitValue(option.value);
      setIsOpen(false);
      inputRef.current?.focus();
    },
    [value, emitValue, setInputValue, setIsOpen, setHighlightedIndex]
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
        setInputValue("");
        setHighlightedIndex(-1);
      }
      return newOpen;
    });
    inputRef.current?.focus();
  }, [disabled, setIsOpen, setInputValue, setHighlightedIndex]);

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
  });

  return (
    <div ref={setRootRef} className="opal-input-single-select">
      <>
        <InputTypeIn
          ref={inputRef}
          name={name}
          placeholder={placeholder}
          value={inputValue}
          onChange={handleInputChange}
          onFocus={handleFocus}
          onClick={() => {
            // Reopen on click while already focused (e.g. after Escape) —
            // focus alone won't fire again. The text stays for editing.
            if (!isOpen) {
              setInputValue(selectedLabel);
              setIsOpen(true);
              setHighlightedIndex(-1);
            }
          }}
          onKeyDown={(event) => {
            if (
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
          placeholder={placeholder}
          sections={visibleSections}
          emptySet={options.length === 0}
          value={value}
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
          inputValue={inputValue}
          allowCreate={!strict}
          showCreateOption={showCreateOption}
          dropdownMaxHeight={dropdownMaxHeight}
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
};

export { InputSingleSelect };
