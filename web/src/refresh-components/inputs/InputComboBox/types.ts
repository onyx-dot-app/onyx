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
