import { useState, useEffect } from "react";
import { ComboBoxOption } from "../types";

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

  // State synchronization logic
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
