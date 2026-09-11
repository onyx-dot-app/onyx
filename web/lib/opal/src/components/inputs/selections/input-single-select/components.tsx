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

import React, {
  useCallback,
  useContext,
  useMemo,
  useRef,
  useId,
  useEffect,
} from "react";
import {
  useFloating,
  autoUpdate,
  flip,
  offset,
  shift,
  size,
} from "@floating-ui/react-dom";
import { useOpalStrings } from "@opal/strings";
import { cn, noProp } from "@opal/utils";
import { InputTypeIn } from "@opal/components";
import { FieldContext } from "@opal/form";
import { Button } from "@opal/components";
import { FieldMessage } from "@opal/form";

// Hooks
import {
  useSelectState,
  useSelectKeyboard,
  filterSections,
  flattenSections,
  normalizeSections,
} from "../shared";
import { useClickOutside } from "@opal/hooks/useClickOutside";
import { useValidation } from "./validation";
import { buildAriaAttributes } from "../dropdown/aria";

// Components
import { SelectDropdown } from "../dropdown/SelectDropdown";

// Types
import { InputSingleSelectProps, SelectOption } from "../types";
import { SvgChevronDown, SvgChevronUp } from "@opal/icons";
import type { WithoutStyles } from "@opal/types";

const InputSingleSelect = ({
  value,
  onChange,
  onValueChange,
  options: optionsProp = [],
  mode = "closed",
  disabled = false,
  placeholder,
  isError: externalIsError,
  onValidationError,
  name,
  searchIcon = false,
  rightChildren,
  separatorLabel,
  createPrefix,
  showOtherOptions = false,
  dropdownMaxHeight,
  ...rest
}: WithoutStyles<InputSingleSelectProps>) => {
  const strict = mode !== "open";
  const sections = useMemo(() => normalizeSections(optionsProp), [optionsProp]);
  const options = useMemo(() => flattenSections(sections), [sections]);
  const strings = useOpalStrings();
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const fieldContext = useContext(FieldContext);

  const hasOptions = options.length > 0;

  //State Management Hook
  const {
    isOpen,
    setIsOpen,
    inputValue,
    setInputValue,
    highlightedIndex,
    setHighlightedIndex,
    isKeyboardNav,
    setIsKeyboardNav,
  } = useSelectState({ value, options });

  // Filtering: each section filters independently; empty ones disappear.
  const hasSearchTerm = inputValue.trim() !== "";
  const visibleSections = useMemo(() => {
    const filtered = filterSections(sections, inputValue);
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
    sections,
    inputValue,
    hasSearchTerm,
    showOtherOptions,
    options,
    separatorLabel,
    strings,
  ]);

  // Whether to show the create option (always show when typing in non-strict mode)
  const showCreateOption = !strict && hasSearchTerm && inputValue.trim() !== "";

  // Combined list for keyboard navigation (includes create option when shown)
  // Only show matched options when searching (hide unmatched)
  const allVisibleOptions = useMemo(() => {
    const baseOptions = flattenSections(visibleSections);
    if (showCreateOption) {
      // Prepend a synthetic option for the "create new" item
      return [{ value: inputValue, label: inputValue }, ...baseOptions];
    }
    return baseOptions;
  }, [visibleSections, showCreateOption, inputValue]);

  // Floating UI for dropdown positioning
  const { refs, floatingStyles } = useFloating({
    open: isOpen,
    placement: "bottom-start",
    middleware: [
      offset(4),
      flip(),
      shift({ padding: 8 }),
      size({
        apply({ rects, elements }) {
          Object.assign(elements.floating.style, {
            width: `${rects.reference.width}px`,
          });
        },
      }),
    ],
    whileElementsMounted: autoUpdate,
  });

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

      // Only call onChange while typing (for controlled input behavior)
      // onValueChange is only called when selecting from dropdown
      onChange?.(e);

      // Open dropdown when user starts typing and there are options
      if (hasOptions && !isOpen) {
        setIsOpen(true);
      }

      // Auto-highlight first match when typing
      setHighlightedIndex(0);
      setIsKeyboardNav(false); // Reset keyboard navigation mode when typing
    },
    [
      onChange,
      hasOptions,
      isOpen,
      setInputValue,
      setIsOpen,
      setHighlightedIndex,
      setIsKeyboardNav,
    ]
  );

  const handleOptionSelect = useCallback(
    (option: SelectOption) => {
      if (option.disabled) return;

      setInputValue(option.value);

      // Support both onChange (event) and onValueChange (value) patterns
      if (onChange) {
        const syntheticEvent = {
          target: { value: option.value },
          currentTarget: { value: option.value },
          type: "change",
          bubbles: true,
          cancelable: true,
        } as React.ChangeEvent<HTMLInputElement>;
        onChange(syntheticEvent);
      }

      onValueChange?.(option.value);

      setIsOpen(false);
      inputRef.current?.focus();
    },
    [onChange, onValueChange, setInputValue, setIsOpen]
  );

  // Keyboard Navigation Hook
  const { handleKeyDown } = useSelectKeyboard({
    isOpen,
    setIsOpen,
    highlightedIndex,
    setHighlightedIndex,
    setIsKeyboardNav,
    allVisibleOptions,
    onSelect: handleOptionSelect,
    hasOptions,
  });

  // Click Outside Hook
  useClickOutside<HTMLElement>(
    [
      inputRef as React.RefObject<HTMLElement>,
      dropdownRef as React.RefObject<HTMLElement>,
    ],
    useCallback(() => {
      setIsOpen(false);
      setIsKeyboardNav(false);
    }, [setIsOpen, setIsKeyboardNav]),
    isOpen
  );

  // The selection's visible text, used to seed editing: focusing must not
  // wipe what the user picked, and the raw value would filter wrongly.
  const selectedLabel = useMemo(() => {
    if (!value) return "";
    return options.find((opt) => opt.value === value)?.label ?? value;
  }, [options, value]);

  const handleFocus = useCallback(() => {
    if (hasOptions) {
      setInputValue(selectedLabel);
      setIsOpen(true);
      setHighlightedIndex(-1);
      setIsKeyboardNav(false);
      // Caret at the end, ready to modify.
      requestAnimationFrame(() => {
        const el = inputRef.current;
        if (el) el.setSelectionRange(el.value.length, el.value.length);
      });
    }
  }, [
    hasOptions,
    selectedLabel,
    setInputValue,
    setIsOpen,
    setHighlightedIndex,
    setIsKeyboardNav,
  ]);

  const toggleDropdown = useCallback(() => {
    if (!disabled && hasOptions) {
      setIsOpen((prev) => {
        const newOpen = !prev;
        if (newOpen) {
          setInputValue("");
          setHighlightedIndex(-1);
        }
        return newOpen;
      });
      inputRef.current?.focus();
    }
  }, [disabled, hasOptions, setIsOpen, setInputValue, setHighlightedIndex]);

  const autoId = useId();
  const fieldId = fieldContext?.baseId || name || `combo-box-${autoId}`;

  // ARIA Attributes Builder
  const ariaProps = buildAriaAttributes({
    hasOptions,
    isOpen,
    isValid,
    highlightedIndex,
    fieldId,
    allVisibleOptions,
    placeholder,
  });

  // Get display label for the current value
  const displayLabel = useMemo(() => {
    // If dropdown is open, show what user is typing
    if (isOpen) return inputValue;

    // When closed, show the matched option label or the value
    if (!value || !hasOptions) return inputValue;
    const option = options.find((opt) => opt.value === value);
    return option ? option.label : inputValue;
  }, [isOpen, inputValue, value, options, hasOptions]);

  return (
    <div ref={refs.setReference} className="relative w-full">
      <>
        <InputTypeIn
          ref={inputRef}
          name={name}
          placeholder={placeholder}
          value={displayLabel}
          onChange={handleInputChange}
          onFocus={handleFocus}
          onClick={() => {
            // Reopen on click while already focused (e.g. after Escape) —
            // focus alone won't fire again. The text stays for editing.
            if (hasOptions && !isOpen) {
              setIsOpen(true);
              setHighlightedIndex(-1);
            }
          }}
          onKeyDown={handleKeyDown}
          variant={disabled ? "disabled" : !isValid ? "error" : undefined}
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
              {hasOptions && (
                <Button
                  disabled={disabled}
                  prominence="tertiary"
                  size="sm"
                  onClick={noProp(toggleDropdown)}
                  icon={isOpen ? SvgChevronUp : SvgChevronDown}
                  aria-label={
                    isOpen ? strings.comboBoxClose : strings.comboBoxOpen
                  }
                  tabIndex={-1}
                  type="button"
                />
              )}
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
          setFloatingRef={refs.setFloating}
          fieldId={fieldId}
          placeholder={placeholder}
          sections={visibleSections}
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
          createPrefix={createPrefix}
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
