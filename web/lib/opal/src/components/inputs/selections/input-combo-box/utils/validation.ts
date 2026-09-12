import { useMemo, useEffect } from "react";
import { ComboBoxOption } from "../types";

interface UseValidationProps {
  value: string;
  options: ComboBoxOption[];
  strict: boolean;
  externalIsError?: boolean;
  onValidationError?: (errorMessage: string | null) => void;
}

interface ValidationResult {
  isValid: boolean;
  errorMessage: string | null;
}

/**
 * Handles validation logic for the ComboBox
 * Supports both external error state and internal strict mode validation
 * external error state has precedence over internal validation.When we have external error, internal error is
 * not displayed we need to display external error separately
 */
export function useValidation({
  value,
  options,
  strict,
  externalIsError,
  onValidationError,
}: UseValidationProps): ValidationResult {
  const hasOptions = options.length > 0;

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

  return { isValid, errorMessage };
}
