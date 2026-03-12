import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { ComboBoxOption } from "./types";

// =============================================================================
// HOOK: useComboBoxState
// =============================================================================

interface UseComboBoxStateProps {
  value: string;
  options: ComboBoxOption[];
}

/**
 * Manages the internal state of the ComboBox component
 * Handles state synchronization between external value prop and internal input state
 */
export function useComboBoxState({ value, options }: UseComboBoxStateProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [inputValue, setInputValue] = useState(value);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [isKeyboardNav, setIsKeyboardNav] = useState(false);
  const prevIsOpenRef = useRef(false);

<<<<<<< voice-mode
  // State synchronization logic
  useEffect(() => {
    const justOpened = isOpen && !prevIsOpenRef.current;
    const justClosed = !isOpen && prevIsOpenRef.current;
    prevIsOpenRef.current = isOpen;

    if (justClosed) {
      // When closing, sync back to the prop value
      setInputValue(value);
    } else if (justOpened) {
      // When first opening, show the label of the matched option (for better UX)
      // This prevents showing raw IDs when the user clicks to open the dropdown
      const matchedOption = options.find((opt) => opt.value === value);
      if (matchedOption) {
        setInputValue(matchedOption.label);
      } else {
=======
  // Sync inputValue with the external value prop.
  // When the dropdown is closed, always reflect the controlled value.
  // When the dropdown is open, only sync if the *value prop itself* changes
  // (e.g. parent programmatically updates it), not when inputValue changes
  // (e.g. user clears the field on focus to browse all options).
  useEffect(() => {
    if (!isOpen) {
      setInputValue(value);
    }
  }, [value, isOpen]);

  useEffect(() => {
    if (isOpen) {
      const isExactOptionMatch = options.some((opt) => opt.value === value);
      if (isExactOptionMatch) {
>>>>>>> main
        setInputValue(value);
      }
    } else if (!isOpen) {
      // While closed, keep in sync with prop value
      setInputValue(value);
    }
<<<<<<< voice-mode
    // Note: While open, we don't sync - let the user type freely
  }, [value, isOpen, options]);
=======
    // Only react to value prop changes while open, not inputValue changes
  }, [value]);
>>>>>>> main

  // Reset highlight and keyboard nav when closing dropdown
  useEffect(() => {
    if (!isOpen) {
      setHighlightedIndex(-1);
      setIsKeyboardNav(false);
    }
  }, [isOpen]);

  return {
    isOpen,
    setIsOpen,
    inputValue,
    setInputValue,
    highlightedIndex,
    setHighlightedIndex,
    isKeyboardNav,
    setIsKeyboardNav,
  };
}

// =============================================================================
// HOOK: useComboBoxKeyboard
// =============================================================================

interface UseComboBoxKeyboardProps {
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
  highlightedIndex: number;
  setHighlightedIndex: (index: number | ((prev: number) => number)) => void;
  setIsKeyboardNav: (isKeyboard: boolean) => void;
  allVisibleOptions: ComboBoxOption[];
  onSelect: (option: ComboBoxOption) => void;
  hasOptions: boolean;
}

/**
 * Manages keyboard navigation for the ComboBox
 * Handles arrow keys, Enter, Escape, and Tab
 */
export function useComboBoxKeyboard({
  isOpen,
  setIsOpen,
  highlightedIndex,
  setHighlightedIndex,
  setIsKeyboardNav,
  allVisibleOptions,
  onSelect,
  hasOptions,
}: UseComboBoxKeyboardProps) {
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
          // Always prevent default and stop propagation when dropdown is open
          // to avoid bubbling to parent forms
          if (isOpen) {
            e.preventDefault();
            e.stopPropagation();
            if (highlightedIndex >= 0) {
              const option = allVisibleOptions[highlightedIndex];
              if (option) {
                onSelect(option);
              }
            }
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
      onSelect,
      setIsOpen,
      setHighlightedIndex,
      setIsKeyboardNav,
    ]
  );

  return { handleKeyDown };
}

// =============================================================================
// HOOK: useOptionFiltering
// =============================================================================

interface UseOptionFilteringProps {
  options: ComboBoxOption[];
  inputValue: string;
}

interface FilterResult {
  matchedOptions: ComboBoxOption[];
  unmatchedOptions: ComboBoxOption[];
  hasSearchTerm: boolean;
}

/**
 * Filters options based on input value
 * Splits options into matched and unmatched for better UX
 */
export function useOptionFiltering({
  options,
  inputValue,
}: UseOptionFilteringProps): FilterResult {
  return useMemo(() => {
    if (!options.length) {
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
  }, [options, inputValue]);
}
