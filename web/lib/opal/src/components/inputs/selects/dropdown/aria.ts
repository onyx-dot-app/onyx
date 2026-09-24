import { SelectOption } from "../types";

/**
 * Sanitizes a value for use in HTML element IDs.
 * Encodes characters that are invalid in IDs (spaces, special chars).
 */
export function sanitizeOptionId(value: string): string {
  return `option-${encodeURIComponent(value)}`;
}

interface BuildAriaAttributesProps {
  isOpen: boolean;
  isValid: boolean;
  highlightedIndex: number;
  fieldId: string;
  allVisibleOptions: SelectOption[];
  placeholder: string;
}

/**
 * Builds ARIA attributes for accessibility
 * Ensures proper screen reader support
 */
export function buildAriaAttributes({
  isOpen,
  isValid,
  highlightedIndex,
  fieldId,
  allVisibleOptions,
  placeholder,
}: BuildAriaAttributesProps) {
  const activeOption =
    isOpen && highlightedIndex >= 0
      ? allVisibleOptions[highlightedIndex]
      : undefined;

  return {
    "aria-label": placeholder,
    "aria-invalid": !isValid,
    "aria-describedby": !isValid ? `${fieldId}-error` : undefined,
    "aria-expanded": isOpen,
    "aria-haspopup": "listbox" as const,
    "aria-controls": `${fieldId}-listbox`,
    "aria-activedescendant": activeOption
      ? `${fieldId}-option-${sanitizeOptionId(activeOption.value)}`
      : undefined,
    "aria-autocomplete": "list" as const,
    role: "combobox" as const,
  };
}
