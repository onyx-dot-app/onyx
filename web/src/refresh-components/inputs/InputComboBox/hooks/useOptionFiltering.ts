import { useMemo } from "react";
import { ComboBoxOption } from "../types";

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
