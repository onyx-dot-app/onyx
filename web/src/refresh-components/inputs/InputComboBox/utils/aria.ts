import { ComboBoxOption } from "../types";

/**
 * Sanitizes a value for use in HTML element IDs.
 * Encodes characters that are invalid in IDs (spaces, special chars).
 */
export function sanitizeOptionId(value: string): string {
  return `option-${encodeURIComponent(value)}`;
}

interface BuildAriaAttributesProps {
  hasOptions: boolean;
  isOpen: boolean;
  isValid: boolean;
  highlightedIndex: number;
  fieldId: string;
  allVisibleOptions: ComboBoxOption[];
  placeholder: string;
}

/**
 * Builds ARIA attributes for accessibility
 * Ensures proper screen reader support
 */
export function buildAriaAttributes({
  hasOptions,
  isOpen,
  isValid,
  highlightedIndex,
  fieldId,
  allVisibleOptions,
  placeholder,
}: BuildAriaAttributesProps) {
  const activeOption =
    hasOptions && isOpen && highlightedIndex >= 0
      ? allVisibleOptions[highlightedIndex]
      : undefined;

  return {
    "aria-label": placeholder,
    "aria-invalid": !isValid,
    "aria-describedby": !isValid ? `${fieldId}-error` : undefined,
    "aria-expanded": hasOptions ? isOpen : undefined,
    "aria-haspopup": hasOptions ? ("listbox" as const) : undefined,
    "aria-controls": hasOptions ? `${fieldId}-listbox` : undefined,
    "aria-activedescendant": activeOption
      ? `${fieldId}-option-${sanitizeOptionId(activeOption.value)}`
      : undefined,
    "aria-autocomplete": hasOptions ? ("list" as const) : undefined,
    role: hasOptions ? ("combobox" as const) : undefined,
  };
}
