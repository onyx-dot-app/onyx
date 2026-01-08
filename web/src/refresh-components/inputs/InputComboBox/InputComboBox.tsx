"use client";

/**
 * InputComboBox - A flexible combo box component that combines input and select functionality
 *
 * Features:
 * - Dual mode: Acts as input when no options, acts as filterable select with options
 * - Automatic filtering based on user input
 * - Strict/non-strict mode: Controls whether only option values are allowed
 * - Built-in validation with inline error display
 * - Full accessibility with ARIA support
 * - Integrates with FormField and form libraries
 * - Based on InputTypeIn with dropdown functionality
 * - **InputSelect API compatible**: Can be used as a drop-in replacement for InputSelect
 *
 * @example Basic Usage - Input Mode (no options)
 * ```tsx
 * const [value, setValue] = useState("");
 *
 * <InputComboBox
 *   placeholder="Enter or select"
 *   value={value}
 *   onChange={(e) => setValue(e.target.value)}
 * />
 * ```
 *
 * @example Select Mode with Filtering
 * ```tsx
 * const options = [
 *   { value: "apple", label: "Apple" },
 *   { value: "banana", label: "Banana" },
 * ];
 *
 * <InputComboBox
 *   placeholder="Select fruit"
 *   value={value}
 *   onChange={(e) => setValue(e.target.value)}
 *   options={options}
 *   strict={true}
 * />
 * ```
 *
 * @example InputSelect-compatible API (drop-in replacement)
 * ```tsx
 * // Works exactly like InputSelect but with filtering capability
 * // onValueChange is only called when user selects from dropdown
 * <InputComboBox
 *   value={model}
 *   onValueChange={(value) => {
 *     setModel(value);
 *     testApiKey(value); // Only called when option is selected
 *   }}
 *   options={modelOptions}
 *   placeholder="Select model"
 *   isError={!!error}
 *   rightSection={<RefreshButton />}
 * />
 * ```
 *
 * @example With FormField Integration
 * ```tsx
 * <FormField state={error ? "error" : "idle"}>
 *   <FormField.Label>Country</FormField.Label>
 *   <FormField.Control asChild>
 *     <InputComboBox
 *       placeholder="Select or type country"
 *       value={country}
 *       onChange={(e) => setCountry(e.target.value)}
 *       options={countryOptions}
 *       strict={false}
 *       onValidationError={setError}
 *     />
 *   </FormField.Control>
 * </FormField>
 * ```
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
import { cn, noProp } from "@/lib/utils";
import InputTypeIn from "../InputTypeIn";
import { FieldContext } from "../../form/FieldContext";
import IconButton from "@/refresh-components/buttons/IconButton";
import { FieldMessage } from "../../messages/FieldMessage";

// Hooks
import {
  useComboBoxState,
  useComboBoxKeyboard,
  useOptionFiltering,
} from "./hooks";
import { useClickOutside } from "@/hooks/useClickOutside";
import { useValidation } from "./utils/validation";
import { buildAriaAttributes } from "./utils/aria";

// Components
import { ComboBoxDropdown } from "./components/ComboBoxDropdown";

// Types
import { InputComboBoxProps, ComboBoxOption } from "./types";
import { SvgChevronDown, SvgChevronUp } from "@opal/icons";

const InputComboBox = ({
  value,
  onChange,
  onValueChange,
  options = [],
  strict = false,
  disabled = false,
  placeholder,
  isError: externalIsError,
  onValidationError,
  name,
  leftSearchIcon = false,
  rightSection,
  separatorLabel = "Other options",
  className,
  ...rest
}: InputComboBoxProps) => {
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
  } = useComboBoxState({ value, options });

  // Filtering Hook
  const { matchedOptions, unmatchedOptions, hasSearchTerm } =
    useOptionFiltering({ options, inputValue });

  // Whether to show the create option (only when no partial matches)
  const showCreateOption =
    !strict &&
    hasSearchTerm &&
    inputValue.trim() !== "" &&
    matchedOptions.length === 0;

  // Combined list for keyboard navigation (includes create option when shown)
  const allVisibleOptions = useMemo(() => {
    const baseOptions = [...matchedOptions, ...unmatchedOptions];
    if (showCreateOption) {
      // Prepend a synthetic option for the "create new" item
      return [{ value: inputValue, label: inputValue }, ...baseOptions];
    }
    return baseOptions;
  }, [matchedOptions, unmatchedOptions, showCreateOption, inputValue]);

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
    (option: ComboBoxOption) => {
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
    (option: ComboBoxOption) => {
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
  const { handleKeyDown } = useComboBoxKeyboard({
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

  const handleFocus = useCallback(() => {
    if (hasOptions) {
      setIsOpen(true);
      setHighlightedIndex(-1); // Start with no highlight on focus
      setIsKeyboardNav(false); // Start with mouse mode
    }
  }, [hasOptions, setIsOpen, setHighlightedIndex, setIsKeyboardNav]);

  const toggleDropdown = useCallback(() => {
    if (!disabled && hasOptions) {
      setIsOpen((prev) => {
        const newOpen = !prev;
        if (newOpen) {
          setHighlightedIndex(-1); // Reset highlight when opening
        }
        return newOpen;
      });
      inputRef.current?.focus();
    }
  }, [disabled, hasOptions, setIsOpen, setHighlightedIndex]);

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
    <div ref={refs.setReference} className={cn("relative w-full", className)}>
      <>
        <InputTypeIn
          ref={inputRef}
          placeholder={placeholder}
          value={displayLabel}
          onChange={handleInputChange}
          onFocus={handleFocus}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          error={!isValid}
          leftSearchIcon={leftSearchIcon}
          showClearButton={false}
          rightSection={
            <>
              {rightSection && (
                <div
                  className="flex items-center"
                  onPointerDown={(e) => {
                    e.stopPropagation();
                  }}
                  onClick={(e) => {
                    e.stopPropagation();
                  }}
                >
                  {rightSection}
                </div>
              )}
              {hasOptions && (
                <IconButton
                  internal
                  onClick={noProp(toggleDropdown)}
                  disabled={disabled}
                  icon={isOpen ? SvgChevronUp : SvgChevronDown}
                  aria-label={isOpen ? "Close dropdown" : "Open dropdown"}
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
        <ComboBoxDropdown
          ref={dropdownRef}
          isOpen={isOpen}
          disabled={disabled}
          floatingStyles={floatingStyles}
          setFloatingRef={refs.setFloating}
          fieldId={fieldId}
          placeholder={placeholder}
          matchedOptions={matchedOptions}
          unmatchedOptions={unmatchedOptions}
          hasSearchTerm={hasSearchTerm}
          separatorLabel={separatorLabel}
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
          isExactMatch={isExactMatch}
          inputValue={inputValue}
          allowCreate={!strict}
          showCreateOption={showCreateOption}
        />
      </>

      {/* Error message - only show internal error messages when not using external isError */}
      {!isValid && errorMessage && externalIsError === undefined && (
        <FieldMessage variant="error" className="ml-0.5 mt-1">
          <FieldMessage.Content
            id={`${fieldId}-error`}
            role="alert"
            className="ml-0.5"
          >
            {errorMessage}
          </FieldMessage.Content>
        </FieldMessage>
      )}
    </div>
  );
};

export default InputComboBox;
