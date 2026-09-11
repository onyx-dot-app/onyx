import type { IconFunctionComponent } from "@opal/types";

export type SelectOption = {
  value: string;
  label: string;
  description?: string;
  icon?: IconFunctionComponent;
  disabled?: boolean;
};

/**
 * A titled slice of the dropdown. Sections render in order with a Divider
 * between each; a section whose options all filter out disappears, so
 * separators never dangle.
 */
export type SelectSection = {
  label?: string;
  options: SelectOption[];
};

/**
 * Without options the field is a plain input — inherently an open set — so
 * only `"open"` may be stated there. With options, `mode` picks the set's
 * openness: "closed" (default) permits only option values; "open" also
 * commits raw text via the create row.
 */
export type InputSingleSelectOptionsProps =
  | {
      options?: never;
      mode?: "open";
    }
  | {
      /** Options, flat or sectioned. Sections render with a Divider between them. */
      options: SelectOption[] | SelectSection[];
      mode?: "closed" | "open";
    };

export type InputSingleSelectProps = InputSingleSelectOptionsProps &
  Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> & {
    /** Current value */
    value: string;
    /** Change handler (React event style) - Called on every keystroke */
    onChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
    /** Change handler (direct value style, for InputSingleSelect compatibility) - Only called when option is selected from dropdown */
    onValueChange?: (value: string) => void;

    /** Disabled state */
    disabled?: boolean;
    /** Placeholder text */
    placeholder: string;
    /** External error state (for InputSingleSelect compatibility) - overrides internal validation */
    isError?: boolean;
    /** Callback to handle validation errors - integrates with form libraries */
    onValidationError?: (errorMessage: string | null) => void;
    /** Optional name for the field (for accessibility) */
    name?: string;
    /** Left search icon */
    searchIcon?: boolean;
    /** Right content slot for custom UI elements (e.g., refresh button) */
    rightChildren?: React.ReactNode;
    /** Label for the separator between matched and unmatched options */
    separatorLabel?: string;
    /** Prefix shown before the typed value in the create option (e.g., "Use", "Add"). When omitted, the raw value is shown without a prefix. */
    createPrefix?: string;
    /**
     * When true, keep non-matching options visible under a separator while searching.
     * Defaults to false so search results are strictly filtered.
     */
    showOtherOptions?: boolean;
    /** Max height of the dropdown in CSS units. Defaults to "15rem". */
    dropdownMaxHeight?: string;
  };
