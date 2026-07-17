"use client";

import * as React from "react";
import {
  Button,
  InputTypeIn,
  type InputTypeInProps,
  Text,
} from "@opal/components";
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
   * Masked-state presentation (Figma Input/Type-In masked value).
   * - `"asterisk"` (default): full-size ✱ glyphs while the field is hidden
   *   and idle, drawn by an overlay (native masking can only render browser
   *   dots). Focus anywhere in the field shows full-size native dots so the
   *   caret tracks real glyph advances while typing.
   * - `"native"`: the browser's own dots (Chromium masks via
   *   -webkit-text-security: disc) at the field's normal text size, so the
   *   caret and dots never change size on reveal. For the login flow.
   */
  mask?: "asterisk" | "native";
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
 * save-password. The masked presentation is gated by the `mask` prop (see its
 * docs): an idle ✱ overlay by default, or the browser's own dots.
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
  mask = "asterisk",
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

  const isNativeMask = mask === "native";
  // The ✱ presentation only draws while idle. Focus anywhere in the field
  // shows native dots, so the caret tracks real glyph advances while typing.
  const showAsteriskOverlay =
    !isNativeMask && isHidden && hasValue && !isFocused;

  return (
    <div
      ref={containerRef}
      // Asterisk mask: the wrapper takes a real box (not `contents`) so the
      // ✱ overlay can anchor over the input, whose text hides underneath.
      // Native mask leaves the input's text size alone, so the caret and
      // dots stay the same size whether hidden or revealed.
      // ph-no-capture is posthog-js's native replay blockClass, so revealed
      // secrets stay out of session replay without server-side config.
      className={cn(
        isNativeMask ? "contents" : "relative w-full",
        "ph-no-capture",
        showAsteriskOverlay && "[&_input]:opacity-0"
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
      {showAsteriskOverlay && (
        // Left inset = .opal-input border (1px) + padding (5px), and Text's
        // px-[2px] mirrors .opal-input-field's p-0.5, so the glyphs line up
        // with the hidden input text. The right inset clears the toggle.
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-0 left-[6px] right-10 flex items-center overflow-hidden"
        >
          <Text font="main-ui-body" color="text-04" nowrap>
            {"✱".repeat(realValue.length)}
          </Text>
        </div>
      )}
    </div>
  );
}

export { PasswordInputTypeIn, type PasswordInputTypeInProps };
