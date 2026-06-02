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
 * save-password. The browser draws its own mask glyph — a filled dot rendered
 * larger than a literal • bullet (closest to ● U+25CF in Chromium) and much
 * wider than normal text. While masked we shrink the field (and its ●
 * placeholder) to a smaller font-size so the dots are tighter and the empty
 * (placeholder) and filled (masked) states match. Callers that show a
 * masked-style placeholder should use ●.
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
      // The native mask glyph is much wider than text, so while hidden we shrink
      // the dots to 0.6rem. We set the size on the input itself (and its ●
      // placeholder) with !important — beating Opal's `font: inherit` / absolute
      // placeholder size — rather than on `.opal-input`, which carries Opal's
      // `transition-all`; keeping the change off that element makes toggling
      // reveal instant instead of animating. rem (not em) avoids compounding, so
      // the same value matches on both the placeholder and the mask. Only while
      // hidden, so revealed text is full-size.
      className={cn(
        "contents",
        isHidden &&
          "[&_input]:!text-[0.6rem] [&_input::placeholder]:!text-[0.6rem]"
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
        // Default to "new-password" so managers don't autofill the user's saved
        // login into secret fields (connector creds, API keys, …). "off" won't
        // do it — browsers deliberately ignore autocomplete="off" on password
        // inputs. The login form overrides this with "current-password".
        autoComplete="new-password"
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
