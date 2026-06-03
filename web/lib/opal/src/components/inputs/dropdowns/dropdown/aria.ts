import type { NavItem } from "../shared";

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
  items: NavItem[];
  placeholder?: string;
  /**
   * Whether the trigger is a text input that filters the list. A button
   * trigger has no autocomplete to announce.
   */
  typeIn?: boolean;
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
  items,
  placeholder,
  typeIn = true,
}: BuildAriaAttributesProps) {
  const active =
    isOpen && highlightedIndex >= 0 ? items[highlightedIndex] : undefined;
  const activeId =
    active?.kind === "option"
      ? `${fieldId}-option-${sanitizeOptionId(active.option.value)}`
      : active?.kind === "group" && active.group.title !== undefined
        ? `${fieldId}-group-${sanitizeOptionId(active.group.title)}`
        : undefined;

  return {
    "aria-label": placeholder,
    "aria-invalid": !isValid,
    "aria-describedby": !isValid ? `${fieldId}-error` : undefined,
    "aria-expanded": isOpen,
    "aria-haspopup": "listbox" as const,
    "aria-controls": `${fieldId}-listbox`,
    "aria-activedescendant": activeId,
    "aria-autocomplete": typeIn ? ("list" as const) : undefined,
    role: "combobox" as const,
  };
}
