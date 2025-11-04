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
  useEffect,
  useMemo,
  useRef,
  useState,
  useId,
} from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";
import InputTypeIn from "./InputTypeIn";
import { FieldContext } from "../form/FieldContext";
import { ChevronDown, ChevronUp } from "lucide-react";
import SvgXOctagon from "@/icons/x-octagon";
import Text from "../texts/Text";

// Utility: Debounce function for performance optimization
function debounce<T extends (...args: any[]) => any>(
  func: T,
  wait: number
): T & { cancel: () => void } {
  let timeout: NodeJS.Timeout | null = null;

  const debounced = function (this: any, ...args: Parameters<T>) {
    if (timeout) clearTimeout(timeout);
    timeout = setTimeout(() => func.apply(this, args), wait);
  } as T & { cancel: () => void };

  debounced.cancel = () => {
    if (timeout) clearTimeout(timeout);
  };

  return debounced;
}

// Internal component for rendering option items
interface OptionItemProps {
  option: ComboBoxOption;
  index: number;
  fieldId: string;
  isHighlighted: boolean;
  isSelected: boolean;
  isExact: boolean;
  onSelect: (option: ComboBoxOption) => void;
  onMouseEnter: (index: number) => void;
  onMouseMove: () => void;
}

const OptionItem = React.memo(
  ({
    option,
    index,
    fieldId,
    isHighlighted,
    isSelected,
    isExact,
    onSelect,
    onMouseEnter,
    onMouseMove,
  }: OptionItemProps) => {
    return (
      <div
        id={`${fieldId}-option-${option.value}`}
        data-index={index}
        role="option"
        aria-selected={isSelected}
        aria-disabled={option.disabled}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(option);
        }}
        onMouseDown={(e) => {
          e.preventDefault();
        }}
        onMouseEnter={() => onMouseEnter(index)}
        onMouseMove={onMouseMove}
        className={cn(
          "px-3 py-2 cursor-pointer transition-colors",
          "flex flex-col rounded-08",
          isExact && "bg-action-link-01",
          !isExact && isHighlighted && "bg-background-tint-02",
          !isExact && isSelected && "bg-background-tint-02",
          option.disabled &&
            "opacity-50 cursor-not-allowed bg-background-neutral-02",
          !option.disabled && !isExact && "hover:bg-background-tint-02"
        )}
      >
        <span
          className={cn(
            "font-main-ui-action",
            isExact && "text-action-link-05 font-medium",
            !isExact && "text-text-04",
            !isExact && isSelected && "font-medium"
          )}
        >
          {option.label}
        </span>
        {option.description && (
          <span
            className={cn(
              "mt-0.5 font-secondary-body",
              isExact ? "text-action-link-04" : "text-text-03"
            )}
          >
            {option.description}
          </span>
        )}
      </div>
    );
  }
);

OptionItem.displayName = "OptionItem";

export type ComboBoxOption = {
  value: string;
  label: string;
  description?: string;
  disabled?: boolean;
};

export interface InputComboBoxProps
  extends Omit<
    React.InputHTMLAttributes<HTMLInputElement>,
    "onChange" | "value"
  > {
  /** Current value */
  value: string;
  /** Change handler (React event style) - Called on every keystroke */
  onChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
  /** Change handler (direct value style, for InputSelect compatibility) - Only called when option is selected from dropdown */
  onValueChange?: (value: string) => void;
  /** Array of options for select mode */
  options?: ComboBoxOption[];
  /**
   * Strict mode:
   * - true: Only option values allowed (if options exist)
   * - false: User can type anything
   */
  strict?: boolean;
  /** Disabled state */
  disabled?: boolean;
  /** Placeholder text */
  placeholder: string;
  /** External error state (for InputSelect compatibility) - overrides internal validation */
  isError?: boolean;
  /** Callback to handle validation errors - integrates with form libraries */
  onValidationError?: (errorMessage: string | null) => void;
  /** Optional name for the field (for accessibility) */
  name?: string;
  /** Left search icon */
  leftSearchIcon?: boolean;
  /** Right section for custom UI elements (e.g., refresh button) */
  rightSection?: React.ReactNode;
  /** Label for the separator between matched and unmatched options */
  separatorLabel?: string;
}

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
  const [isOpen, setIsOpen] = useState(false);
  const [inputValue, setInputValue] = useState(value);
  const [highlightedIndex, setHighlightedIndex] = useState(-1); // Start with no highlight
  const [isKeyboardNav, setIsKeyboardNav] = useState(false); // Track if user is using keyboard
  const [dropdownPosition, setDropdownPosition] = useState<{
    top: number;
    left: number;
    width: number;
    flipped: boolean;
  } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const fieldContext = useContext(FieldContext);

  const hasOptions = options.length > 0;

  // Filter options based on input - split into matched and unmatched
  const { matchedOptions, unmatchedOptions, hasSearchTerm } = useMemo(() => {
    if (!hasOptions) {
      return { matchedOptions: [], unmatchedOptions: [], hasSearchTerm: false };
    }

    if (!inputValue || !inputValue.trim()) {
      return {
        matchedOptions: options,
        unmatchedOptions: [],
        hasSearchTerm: false,
      };
    }

    const searchTerm = inputValue.toLowerCase().trim();
    const matched: ComboBoxOption[] = [];
    const unmatched: ComboBoxOption[] = [];

    options.forEach((option) => {
      const matchesLabel = option.label.toLowerCase().includes(searchTerm);
      const matchesValue = option.value.toLowerCase().includes(searchTerm);

      if (matchesLabel || matchesValue) {
        matched.push(option);
      } else {
        unmatched.push(option);
      }
    });

    return {
      matchedOptions: matched,
      unmatchedOptions: unmatched,
      hasSearchTerm: true,
    };
  }, [options, inputValue, hasOptions]);

  // Combined list for keyboard navigation
  const allVisibleOptions = useMemo(() => {
    return [...matchedOptions, ...unmatchedOptions];
  }, [matchedOptions, unmatchedOptions]);

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

  // Validation logic - use external error if provided, otherwise use internal validation
  const { isValid, errorMessage } = useMemo(() => {
    // If external error is provided, use it
    if (externalIsError !== undefined) {
      return { isValid: !externalIsError, errorMessage: null };
    }

    // Otherwise use internal validation
    if (!strict || !hasOptions || !value) {
      return { isValid: true, errorMessage: null };
    }

    // In strict mode with options, value must be one of the option values
    const isValidOption = options.some((opt) => opt.value === value);

    if (!isValidOption) {
      return {
        isValid: false,
        errorMessage: "Please select a valid option from the list",
      };
    }

    return { isValid: true, errorMessage: null };
  }, [externalIsError, strict, hasOptions, value, options]);

  // Notify parent of error state
  useEffect(() => {
    onValidationError?.(errorMessage);
  }, [errorMessage, onValidationError]);

  // Sync internal input value with external value
  // Only sync when the dropdown is closed or when value changes significantly
  useEffect(() => {
    // If dropdown is closed, always sync with prop value
    if (!isOpen) {
      setInputValue(value);
    } else {
      // If dropdown is open, only sync if the new value is an exact match with an option
      // This prevents interference when user is typing
      const isExactOptionMatch = options.some((opt) => opt.value === value);
      if (isExactOptionMatch && inputValue !== value) {
        setInputValue(value);
      }
    }
  }, [value, isOpen, options, inputValue]);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node) &&
        inputRef.current &&
        !inputRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
        setIsKeyboardNav(false); // Reset keyboard navigation
      }
    };

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => {
        document.removeEventListener("mousedown", handleClickOutside);
      };
    }
  }, [isOpen]);

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

      // Reset highlighted index to -1 when filtering changes (no initial highlight)
      setHighlightedIndex(-1);
      setIsKeyboardNav(false); // Reset keyboard navigation mode when typing
    },
    [onChange, hasOptions, isOpen]
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
    [onChange, onValueChange]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (!hasOptions) return;

      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setIsKeyboardNav(true); // Mark as keyboard navigation
          if (!isOpen) {
            setIsOpen(true);
            setHighlightedIndex(0);
          } else {
            setHighlightedIndex((prev) => {
              // If no item highlighted yet (-1), start at 0
              if (prev === -1) return 0;
              // Otherwise move down if not at end
              return prev < allVisibleOptions.length - 1 ? prev + 1 : prev;
            });
          }
          break;
        case "ArrowUp":
          e.preventDefault();
          setIsKeyboardNav(true); // Mark as keyboard navigation
          if (isOpen) {
            setHighlightedIndex((prev) => {
              // If at first item or no highlight, don't go further up
              if (prev <= 0) return -1;
              return prev - 1;
            });
          }
          break;
        case "Enter":
          e.preventDefault();
          if (
            isOpen &&
            highlightedIndex >= 0 &&
            allVisibleOptions[highlightedIndex]
          ) {
            handleOptionSelect(allVisibleOptions[highlightedIndex]);
          }
          break;
        case "Escape":
          e.preventDefault();
          setIsOpen(false);
          setIsKeyboardNav(false);
          break;
        case "Tab":
          setIsOpen(false);
          setIsKeyboardNav(false);
          break;
      }
    },
    [
      hasOptions,
      isOpen,
      allVisibleOptions,
      highlightedIndex,
      handleOptionSelect,
    ]
  );

  const handleFocus = useCallback(() => {
    if (hasOptions) {
      setIsOpen(true);
      setHighlightedIndex(-1); // Start with no highlight on focus
      setIsKeyboardNav(false); // Start with mouse mode
    }
  }, [hasOptions]);

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
  }, [disabled, hasOptions]);

  const autoId = useId();
  const fieldId = fieldContext?.baseId || name || `combo-box-${autoId}`;

  // Get display label for the current value
  const displayLabel = useMemo(() => {
    // If dropdown is open, show what user is typing
    if (isOpen) return inputValue;

    // When closed, show the matched option label or the value
    if (!value || !hasOptions) return inputValue;
    const option = options.find((opt) => opt.value === value);
    return option ? option.label : inputValue;
  }, [isOpen, inputValue, value, options, hasOptions]);

  // Calculate dropdown position with collision detection
  const updatePosition = useCallback(() => {
    if (containerRef.current && isOpen) {
      const rect = containerRef.current.getBoundingClientRect();
      const dropdownHeight = 240; // max-h-60 = 15rem = 240px
      const gap = 4; // margin between input and dropdown
      const viewportPadding = 8; // minimum distance from viewport edge

      // Calculate available space
      const spaceBelow = window.innerHeight - rect.bottom;
      const spaceAbove = rect.top;

      // Determine if dropdown should flip above the input
      const shouldFlipUp =
        spaceBelow < dropdownHeight && spaceAbove > spaceBelow;

      // Calculate vertical position
      const top = shouldFlipUp
        ? rect.top + window.scrollY - dropdownHeight - gap
        : rect.bottom + window.scrollY + gap;

      // Calculate horizontal position with boundary constraints
      const left = Math.max(
        viewportPadding,
        Math.min(
          rect.left + window.scrollX,
          window.innerWidth - rect.width - viewportPadding
        )
      );

      setDropdownPosition({
        top,
        left,
        width: rect.width,
        flipped: shouldFlipUp,
      });
    }
  }, [isOpen]);

  // Memoize debounced position updater
  const debouncedUpdatePosition = useMemo(
    () => debounce(updatePosition, 16), // ~60fps
    [updatePosition]
  );

  // Position calculation with debouncing for scroll/resize
  useEffect(() => {
    if (isOpen) {
      updatePosition(); // Immediate on open
      window.addEventListener("scroll", debouncedUpdatePosition, true);
      window.addEventListener("resize", debouncedUpdatePosition);

      return () => {
        debouncedUpdatePosition.cancel();
        window.removeEventListener("scroll", debouncedUpdatePosition, true);
        window.removeEventListener("resize", debouncedUpdatePosition);
      };
    }
  }, [isOpen, updatePosition, debouncedUpdatePosition]);

  // Scroll highlighted option into view
  useEffect(() => {
    if (isOpen && dropdownRef.current && highlightedIndex >= 0) {
      const highlightedElement = dropdownRef.current.querySelector(
        `[data-index="${highlightedIndex}"]`
      );
      if (highlightedElement) {
        highlightedElement.scrollIntoView({
          block: "nearest",
          behavior: "smooth",
        });
      }
    }
  }, [highlightedIndex, isOpen]);

  return (
    <div ref={containerRef} className={cn("relative w-full", className)}>
      <div className="relative">
        <InputTypeIn
          ref={inputRef}
          placeholder={placeholder}
          value={displayLabel}
          onChange={handleInputChange}
          onFocus={handleFocus}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          isError={!isValid}
          leftSearchIcon={leftSearchIcon}
          aria-label={placeholder}
          aria-invalid={!isValid}
          aria-describedby={!isValid ? `${fieldId}-error` : undefined}
          aria-expanded={hasOptions ? isOpen : undefined}
          aria-haspopup={hasOptions ? "listbox" : undefined}
          aria-controls={hasOptions ? `${fieldId}-listbox` : undefined}
          aria-activedescendant={
            hasOptions &&
            isOpen &&
            highlightedIndex >= 0 &&
            allVisibleOptions[highlightedIndex]
              ? `${fieldId}-option-${allVisibleOptions[highlightedIndex].value}`
              : undefined
          }
          aria-autocomplete={hasOptions ? "list" : undefined}
          role={hasOptions ? "combobox" : undefined}
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
                <button
                  type="button"
                  onClick={toggleDropdown}
                  disabled={disabled}
                  className={cn(
                    "flex items-center justify-center p-1 rounded hover:bg-background-neutral-01 transition-colors",
                    disabled && "cursor-not-allowed opacity-50"
                  )}
                  aria-label={isOpen ? "Close dropdown" : "Open dropdown"}
                  tabIndex={-1}
                >
                  {isOpen ? (
                    <ChevronUp className="w-4 h-4 text-text-02" />
                  ) : (
                    <ChevronDown className="w-4 h-4 text-text-02" />
                  )}
                </button>
              )}
            </>
          }
          {...rest}
        />

        {/* Dropdown - Rendered in Portal */}
        {hasOptions &&
          isOpen &&
          !disabled &&
          dropdownPosition &&
          typeof document !== "undefined" &&
          createPortal(
            <div
              ref={dropdownRef}
              id={`${fieldId}-listbox`}
              role="listbox"
              aria-label={placeholder}
              className={cn(
                "fixed z-[9999] bg-background-neutral-00 border border-border-02 rounded-12 shadow-02 max-h-60 overflow-auto p-1"
              )}
              style={{
                top: `${dropdownPosition.top}px`,
                left: `${dropdownPosition.left}px`,
                width: `${dropdownPosition.width}px`,
                marginTop: "4px",
              }}
            >
              {matchedOptions.length > 0 || unmatchedOptions.length > 0 ? (
                <>
                  {/* Matched/Filtered Options */}
                  {matchedOptions.map((option, idx) => {
                    const globalIndex = idx;
                    const isExact = isExactMatch(option);
                    return (
                      <OptionItem
                        key={option.value}
                        option={option}
                        index={globalIndex}
                        fieldId={fieldId}
                        isHighlighted={globalIndex === highlightedIndex}
                        isSelected={value === option.value}
                        isExact={isExact}
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
                      />
                    );
                  })}

                  {/* Separator - only show if there are unmatched options and a search term */}
                  {hasSearchTerm && unmatchedOptions.length > 0 && (
                    <div className="px-3 py-2 pt-3">
                      <div className="border-t border-border-01 pt-2">
                        <Text text04 secondaryBody className="text-text-02">
                          {separatorLabel}
                        </Text>
                      </div>
                    </div>
                  )}

                  {/* Unmatched Options */}
                  {unmatchedOptions.map((option, idx) => {
                    const globalIndex = matchedOptions.length + idx;
                    const isExact = isExactMatch(option);
                    return (
                      <OptionItem
                        key={option.value}
                        option={option}
                        index={globalIndex}
                        fieldId={fieldId}
                        isHighlighted={globalIndex === highlightedIndex}
                        isSelected={value === option.value}
                        isExact={isExact}
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
                      />
                    );
                  })}
                </>
              ) : (
                <div className="px-3 py-2 text-text-02 font-secondary-body">
                  No options found
                </div>
              )}
            </div>,
            document.body
          )}
      </div>

      {/* Error message - only show internal error messages when not using external isError */}
      {!isValid && errorMessage && externalIsError === undefined && (
        <div className="flex flex-row items-center gap-x-0.5 ml-0.5 mt-1">
          <div className="w-4 h-4 flex items-center justify-center">
            <SvgXOctagon className="h-3 w-3 stroke-status-error-05" />
          </div>
          <Text
            id={`${fieldId}-error`}
            text03
            secondaryBody
            className="ml-0.5"
            role="alert"
          >
            {errorMessage}
          </Text>
        </div>
      )}
    </div>
  );
};

export default InputComboBox;
