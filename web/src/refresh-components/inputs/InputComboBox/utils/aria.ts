import { ComboBoxOption } from "../types";

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
  return {
    "aria-label": placeholder,
    "aria-invalid": !isValid,
    "aria-describedby": !isValid ? `${fieldId}-error` : undefined,
    "aria-expanded": hasOptions ? isOpen : undefined,
    "aria-haspopup": hasOptions ? ("listbox" as const) : undefined,
    "aria-controls": hasOptions ? `${fieldId}-listbox` : undefined,
    "aria-activedescendant":
      hasOptions &&
      isOpen &&
      highlightedIndex >= 0 &&
      allVisibleOptions[highlightedIndex]
        ? `${fieldId}-option-${allVisibleOptions[highlightedIndex].value}`
        : undefined,
    "aria-autocomplete": hasOptions ? ("list" as const) : undefined,
    role: hasOptions ? ("combobox" as const) : undefined,
  };
}
