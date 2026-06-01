"use client";

import * as React from "react";
import { InputTypeIn, type InputTypeInProps } from "@opal/components";
import { Button } from "@opal/components";
import { cn } from "@opal/utils";
import { noProp } from "@/lib/utils";
import { SvgEye, SvgEyeClosed } from "@opal/icons";

// Backend placeholder pattern - indicates a stored value that can't be revealed
const BACKEND_PLACEHOLDER_PATTERN = /^•+$/; // All bullet characters (U+2022)

/**
 * Check if a value is a backend placeholder (all bullet characters).
 * The backend sends this to indicate a stored secret exists without revealing it.
 */
function isBackendPlaceholder(value: string): boolean {
  return !!value && BACKEND_PLACEHOLDER_PATTERN.test(value);
}

export interface PasswordInputTypeInProps extends Omit<
  InputTypeInProps,
  "type" | "rightChildren" | "searchIcon" | "variant"
> {
  /**
   * Ref to the input element.
   */
  ref?: React.Ref<HTMLInputElement>;
  /**
   * Whether the input is disabled.
   */
  disabled?: boolean;
  /**
   * Whether the input has an error.
   */
  error?: boolean;
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
 * A native password input (`type="password"`, toggled to `"text"` when
 * revealed) with a reveal/hide toggle. Built on top of InputTypeIn for
 * consistency.
 *
 * Using the native type (rather than a custom-masked `type="text"` field) is
 * what lets browsers and password managers recognize the field for autofill /
 * save-password. The browser draws its own mask glyph (•); we shrink its
 * font-size while masked so it reads as a smaller dot.
 *
 * Features:
 * - Show/hide toggle button only visible when input has value or is focused
 * - When revealed, the toggle icon uses action style (more prominent)
 * - When hidden, the toggle icon uses internal style (muted)
 * - Optional `isNonRevealable` prop to disable reveal (for stored backend values)
 */
export default function PasswordInputTypeIn({
  ref,
  isNonRevealable = false,
  value,
  onChange,
  onFocus,
  onBlur,
  disabled,
  error,
  clearButton = false,
  ...props
}: PasswordInputTypeInProps) {
  const [isPasswordVisible, setIsPasswordVisible] = React.useState(false);
  const [isFocused, setIsFocused] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);

  const realValue = String(value || "");
  const hasValue = realValue.length > 0;
  const effectiveNonRevealable =
    isNonRevealable || isBackendPlaceholder(realValue);
  const isHidden = !isPasswordVisible || effectiveNonRevealable;

  const handleContainerFocus = React.useCallback(() => {
    setIsFocused(true);
  }, []);

  const handleContainerBlur = React.useCallback(
    (e: React.FocusEvent<HTMLDivElement>) => {
      if (containerRef.current?.contains(e.relatedTarget as Node)) {
        return;
      }
      setIsFocused(false);
    },
    []
  );

  const showToggleButton = hasValue || isFocused;
  const isRevealed = isPasswordVisible && !effectiveNonRevealable;
  const toggleLabel = effectiveNonRevealable
    ? "Value cannot be revealed"
    : isPasswordVisible
      ? "Hide password"
      : "Show password";

  return (
    <div
      ref={containerRef}
      // The browser's mask glyph (•) is sized by font-size, which we can't set
      // on the glyph alone — so while the value is hidden we shrink the input's
      // font-size to render smaller dots, restoring full size when revealed.
      className={cn(
        "contents",
        isHidden && hasValue && "[&_.opal-input-field]:text-[0.8em]"
      )}
      onFocus={handleContainerFocus}
      onBlur={handleContainerBlur}
    >
      <InputTypeIn
        ref={ref}
        type={isHidden ? "password" : "text"}
        value={value}
        onChange={onChange}
        onFocus={onFocus}
        onBlur={onBlur}
        variant={disabled ? "disabled" : error ? "error" : undefined}
        clearButton={showToggleButton ? false : clearButton}
        // Default off so admin credential fields don't get the user's login
        // password autofilled into them; real login/signup forms override this
        // with current-password / new-password.
        autoComplete="off"
        data-ph-no-capture
        rightChildren={
          showToggleButton ? (
            <Button
              disabled={disabled || effectiveNonRevealable}
              icon={isRevealed ? SvgEye : SvgEyeClosed}
              onClick={noProp(() => setIsPasswordVisible((v) => !v))}
              type="button"
              variant={isRevealed ? "action" : undefined}
              prominence="tertiary"
              size="sm"
              tooltipSide="left"
              tooltip={toggleLabel}
              aria-label={toggleLabel}
            />
          ) : undefined
        }
        {...props}
      />
    </div>
  );
}
