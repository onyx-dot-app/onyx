"use client";

import * as React from "react";
import InputTypeIn, {
  InputTypeInProps,
} from "@/refresh-components/inputs/InputTypeIn";
import IconButton from "@/refresh-components/buttons/IconButton";
import { noProp } from "@/lib/utils";
import { SvgEye, SvgEyeClosed } from "@opal/icons";

// ASTERISK OPERATOR (U+2217) - better sized than bullet (•)
const MASK_CHARACTER = "∗";

// Backend placeholder pattern - indicates a stored value that can't be revealed
const BACKEND_PLACEHOLDER_PATTERN = /^•+$/; // All bullet characters (U+2022)

/**
 * Check if a value is a backend placeholder (all bullet characters).
 * The backend sends this to indicate a stored secret exists without revealing it.
 */
function isBackendPlaceholder(value: string): boolean {
  return !!value && BACKEND_PLACEHOLDER_PATTERN.test(value);
}

export interface PasswordInputTypeInProps
  extends Omit<InputTypeInProps, "type" | "rightSection" | "leftSearchIcon"> {
  /**
   * When true, the reveal toggle is disabled.
   * Use this when displaying a stored/masked value from the backend
   * that cannot actually be revealed.
   * The input remains editable so users can type a new value.
   */
  isNonRevealable?: boolean;
}

/**
 * PasswordInputTypeIn Component
 *
 * A password input with custom mask character (∗) and reveal/hide toggle.
 * Built on top of InputTypeIn for consistency.
 *
 * Features:
 * - Custom mask character (∗) instead of browser default
 * - Show/hide toggle button only visible when input has value or is focused
 * - When revealed, the toggle icon uses action style (more prominent)
 * - When hidden, the toggle icon uses internal style (muted)
 * - Optional `isNonRevealable` prop to disable reveal (for stored backend values)
 */
const PasswordInputTypeIn = React.forwardRef<
  HTMLInputElement,
  PasswordInputTypeInProps
>(function PasswordInputTypeIn(
  {
    isNonRevealable = false,
    value,
    onChange,
    onFocus,
    onBlur,
    disabled,
    showClearButton = false,
    ...props
  },
  ref
) {
  const [isPasswordVisible, setIsPasswordVisible] = React.useState(false);
  const [isFocused, setIsFocused] = React.useState(false);

  // Track selection range before changes occur
  const selectionRef = React.useRef<{ start: number; end: number }>({
    start: 0,
    end: 0,
  });

  const realValue = String(value || "");
  const hasValue = realValue.length > 0;
  const effectiveNonRevealable =
    isNonRevealable || isBackendPlaceholder(realValue);
  const isHidden = !isPasswordVisible || effectiveNonRevealable;

  const getDisplayValue = (): string => {
    if (isHidden) {
      return MASK_CHARACTER.repeat(realValue.length);
    }
    return realValue;
  };

  const handleFocus = React.useCallback(
    (e: React.FocusEvent<HTMLInputElement>) => {
      setIsFocused(true);
      onFocus?.(e);
    },
    [onFocus]
  );

  const handleBlur = React.useCallback(
    (e: React.FocusEvent<HTMLInputElement>) => {
      setIsFocused(false);
      onBlur?.(e);
    },
    [onBlur]
  );

  // Track selection on any interaction that might change it
  const handleSelect = React.useCallback(
    (e: React.SyntheticEvent<HTMLInputElement>) => {
      const target = e.target as HTMLInputElement;
      selectionRef.current = {
        start: target.selectionStart ?? 0,
        end: target.selectionEnd ?? 0,
      };
    },
    []
  );

  const handleKeyDown = React.useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      const target = e.target as HTMLInputElement;
      selectionRef.current = {
        start: target.selectionStart ?? 0,
        end: target.selectionEnd ?? 0,
      };
    },
    []
  );

  const handleChange = React.useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (!isHidden) {
        onChange?.(e);
        return;
      }

      const input = e.target;
      const newDisplayValue = input.value;
      const cursorPos = input.selectionStart ?? newDisplayValue.length;
      const oldLength = realValue.length;
      const newLength = newDisplayValue.length;

      // Get the selection range from before the change
      const prevSelStart = selectionRef.current.start;
      const prevSelEnd = selectionRef.current.end;
      const hadSelection = prevSelEnd > prevSelStart;

      let newRealValue: string;
      let newCursorPos = cursorPos;

      if (newLength === 0) {
        // Field was cleared
        newRealValue = "";
        newCursorPos = 0;
      } else if (hadSelection) {
        // Text was selected and replaced/deleted
        // Extract non-mask characters from the new display value (these are the inserted chars)
        const insertedChars = newDisplayValue
          .split("")
          .filter((char) => char !== MASK_CHARACTER)
          .join("");

        // Replace the selected portion with the inserted characters
        newRealValue =
          realValue.slice(0, prevSelStart) +
          insertedChars +
          realValue.slice(prevSelEnd);
        newCursorPos = prevSelStart + insertedChars.length;
      } else if (newLength > oldLength) {
        // Characters were added (typed or pasted) without selection
        const charsAdded = newLength - oldLength;
        const insertPos = cursorPos - charsAdded;
        const addedChars = newDisplayValue.slice(insertPos, cursorPos);
        newRealValue =
          realValue.slice(0, insertPos) +
          addedChars +
          realValue.slice(insertPos);
        newCursorPos = cursorPos;
      } else if (newLength < oldLength) {
        // Characters were deleted without selection
        const charsDeleted = oldLength - newLength;
        const deleteStart = cursorPos;
        const deleteEnd = cursorPos + charsDeleted;
        newRealValue =
          realValue.slice(0, deleteStart) + realValue.slice(deleteEnd);
        newCursorPos = cursorPos;
      } else {
        // Same length without selection - shouldn't happen, but handle gracefully
        newRealValue = realValue;
        newCursorPos = cursorPos;
      }

      // Restore cursor position after React re-renders
      requestAnimationFrame(() => {
        if (input && document.activeElement === input) {
          input.setSelectionRange(newCursorPos, newCursorPos);
        }
      });

      // Synthetic event for Formik - only includes essential properties
      const syntheticEvent = {
        target: {
          name: input.name,
          value: newRealValue,
          type: "text",
        },
        currentTarget: {
          name: input.name,
          value: newRealValue,
          type: "text",
        },
        type: "change",
        persist: () => {},
      } as unknown as React.ChangeEvent<HTMLInputElement>;

      onChange?.(syntheticEvent);
    },
    [isHidden, realValue, onChange]
  );

  const showToggleButton = hasValue || isFocused;
  const isRevealed = isPasswordVisible && !effectiveNonRevealable;
  const toggleLabel = effectiveNonRevealable
    ? "Value cannot be revealed"
    : isPasswordVisible
      ? "Hide password"
      : "Show password";

  return (
    <InputTypeIn
      ref={ref}
      value={getDisplayValue()}
      onChange={handleChange}
      onFocus={handleFocus}
      onBlur={handleBlur}
      onSelect={handleSelect}
      onKeyDown={handleKeyDown}
      disabled={disabled}
      showClearButton={showClearButton}
      autoComplete="off"
      rightSection={
        showToggleButton ? (
          <IconButton
            icon={isRevealed ? SvgEye : SvgEyeClosed}
            disabled={disabled || effectiveNonRevealable}
            onClick={noProp(() => setIsPasswordVisible((v) => !v))}
            type="button"
            action={isRevealed}
            internal
            toolTipPosition="left"
            tooltipSize="sm"
            tooltip={toggleLabel}
            aria-label={toggleLabel}
          />
        ) : undefined
      }
      {...props}
    />
  );
});

export default PasswordInputTypeIn;
