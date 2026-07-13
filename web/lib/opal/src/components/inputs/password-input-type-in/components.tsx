"use client";

import * as React from "react";
import { Button, InputTypeIn, type InputTypeInProps } from "@opal/components";
import { cn } from "@opal/utils";
import { SvgEye, SvgEyeClosed } from "@opal/icons";

// Backend placeholder pattern - indicates a stored value that can't be revealed
const BACKEND_PLACEHOLDER_PATTERN = /^•+$/; // All bullet characters (U+2022)

/**
 * Detects the backend's fully-masked stored-secret placeholder (all U+2022
 * bullets). Partially-masked formats like "abcd...wxyz" are not treated as
 * placeholders.
 */
function isBackendPlaceholder(value: string): boolean {
  return !!value && BACKEND_PLACEHOLDER_PATTERN.test(value);
}

interface PasswordInputTypeInProps extends Omit<
  InputTypeInProps,
  "type" | "rightChildren" | "searchIcon" | "variant"
> {
  disabled?: boolean;
  error?: boolean;
  /**
   * When true, the reveal toggle is disabled.
   * Use this when displaying a stored/masked value from the backend
   * that cannot actually be revealed.
   * The input remains editable so users can type a new value.
   * Values of all bullet characters are treated as non-revealable
   * automatically. Use this prop for masked values that pattern does not
   * catch.
   */
  isNonRevealable?: boolean;
  /**
   * When true, the placeholder is shrunk to the same font-size as the masked
   * dots while the field is hidden. Use this only with a masked-style
   * placeholder (all ● glyphs, e.g. the login form) so the empty and filled
   * states line up. Leave false (the default) for custom text placeholders
   * (e.g. "AKIA…", "Your long-term API key") so they stay legible.
   */
  shrinkPlaceholder?: boolean;
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
 * save-password. While masked, Chromium renders the value as U+2022 bullets
 * in the field's own font (-webkit-text-security: disc). The design calls for
 * smaller, tighter dots than full-size bullets, so we shrink the field's
 * font-size while masked. The placeholder is only shrunk to match when the
 * caller opts in via `shrinkPlaceholder` (used with a masked-style bullet
 * placeholder). Custom text placeholders (e.g. "AKIA…", "Your long-term API
 * key") keep their normal size so they stay legible.
 *
 * Features:
 * - Show/hide toggle button only visible when input has value or is focused
 * - When revealed, the toggle icon uses action style (more prominent)
 * - When hidden, the toggle icon uses the default tertiary style (muted)
 * - Optional `isNonRevealable` prop to disable reveal (for stored backend values)
 */
function PasswordInputTypeIn({
  ref,
  isNonRevealable = false,
  shrinkPlaceholder = false,
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
      // While hidden we shrink the mask dots to 0.6rem for tighter spacing.
      // The size goes on the input itself with
      // !important, beating Opal's `font: inherit`, rather than on
      // `.opal-input`, which carries Opal's `transition-all`. Keeping the
      // change off that element makes toggling reveal instant instead of
      // animating. rem (not em) avoids compounding. The placeholder carries
      // its own absolute Opal size, so the input shrink never touches it.
      // It only shrinks (also with !important) when the caller opts in via
      // `shrinkPlaceholder` (masked-style ● placeholder), so it matches the
      // dots. Custom text placeholders stay full-size. Only while hidden, so
      // revealed text is full-size.
      className={cn(
        "contents",
        isHidden && "[&_input]:!text-[0.6rem]",
        isHidden && shrinkPlaceholder && "[&_input::placeholder]:!text-[0.6rem]"
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
        // do it, browsers deliberately ignore autocomplete="off" on password
        // inputs. Login forms should override with "current-password".
        autoComplete="new-password"
        data-ph-no-capture
        rightChildren={
          showToggleButton ? (
            <Button
              disabled={disabled || effectiveNonRevealable}
              icon={isRevealed ? SvgEye : SvgEyeClosed}
              // stopPropagation keeps the nested toggle click off the field.
              onClick={(e) => {
                e.stopPropagation();
                setIsPasswordVisible((v) => !v);
              }}
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

export { PasswordInputTypeIn, type PasswordInputTypeInProps };
