"use client";

import * as React from "react";
import {
  Button,
  InputTypeIn,
  type InputTypeInProps,
  Tag,
} from "@opal/components";
import { cn } from "@opal/utils";
import { SvgEye, SvgEyeClosed, SvgKey } from "@opal/icons";
import { useOpalStrings } from "@opal/strings";

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

type InputPasswordTypeInProps = Omit<
  InputTypeInProps,
  "type" | "rightChildren" | "searchIcon" | "variant" | "clearButton"
> & {
  /** Controls after the reveal toggle, at the field's end (a dropdown chevron). */
  rightChildren?: React.ReactNode;
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
   * A stored value from the backend, already masked. While `value` equals
   * it, the field shows it as a tag that cannot be revealed and treats it as
   * one unit: Backspace or Delete clears it, and typing or pasting replaces
   * it with the new text. Once edited, the field behaves as usual.
   */
  existingValue?: string;
};

/**
 * InputPasswordTypeIn Component
 *
 * A native password input (`type="password"`, toggled to `"text"` when
 * revealed) with a reveal/hide toggle. Built on top of InputTypeIn for
 * consistency.
 *
 * Using the native type (rather than a custom-masked `type="text"` field) is
 * what lets browsers and password managers recognize the field for autofill /
 * save-password. The hidden value shows as the browser's own dots, at the
 * field's normal text size, so the caret and dots never change size on reveal.
 *
 * Features:
 * - Show/hide toggle button, always visible
 * - When revealed, the toggle icon uses action style (more prominent)
 * - When hidden, the toggle icon uses the default tertiary style (muted)
 * - Optional `isNonRevealable` prop to disable reveal (for stored backend values)
 * - Optional `existingValue` prop: a stored value, shown as a tag, that edits
 *   replace whole
 */
function InputPasswordTypeIn({
  ref,
  isNonRevealable = false,
  existingValue,
  value,
  onChange,
  onKeyDown,
  onFocus,
  onBlur,
  disabled,
  error,
  rightChildren,
  leftChildren,
  ...props
}: InputPasswordTypeInProps) {
  const [isPasswordVisible, setIsPasswordVisible] = React.useState(false);
  const strings = useOpalStrings();

  const realValue = String(value || "");
  const hasValue = realValue.length > 0;
  const isExistingValue =
    existingValue !== undefined && hasValue && realValue === existingValue;
  const effectiveNonRevealable =
    isNonRevealable || isExistingValue || isBackendPlaceholder(realValue);
  const isHidden = !isPasswordVisible || effectiveNonRevealable;

  const isRevealed = isPasswordVisible && !effectiveNonRevealable;
  const toggleLabel = effectiveNonRevealable
    ? strings.valueCannotBeRevealed
    : isPasswordVisible
      ? strings.hidePassword
      : strings.showPassword;

  // While the tag shows, the input itself is empty: what the user types is
  // the whole new value, and a deletion clears the existing one.
  const handleKeyDown = React.useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      // The caller's handler runs first, so it can cancel the deletion.
      onKeyDown?.(e);
      if (
        isExistingValue &&
        !props.readOnly &&
        !e.defaultPrevented &&
        (e.key === "Backspace" || e.key === "Delete")
      ) {
        e.preventDefault();
        onChange?.({
          target: { value: "", name: props.name ?? "" },
          currentTarget: { value: "", name: props.name ?? "" },
          type: "change",
          bubbles: true,
          cancelable: true,
        } as React.ChangeEvent<HTMLInputElement>);
      }
    },
    [isExistingValue, onChange, onKeyDown, props.name, props.readOnly]
  );

  return (
    <div
      // ph-no-capture is posthog-js's native replay blockClass, so revealed
      // secrets stay out of session replay without server-side config.
      className="contents ph-no-capture"
    >
      <InputTypeIn
        ref={ref}
        type={isHidden ? "password" : "text"}
        value={isExistingValue ? "" : value}
        onChange={onChange}
        onKeyDown={handleKeyDown}
        onFocus={onFocus}
        onBlur={onBlur}
        variant={disabled ? "disabled" : error ? "error" : undefined}
        // Default to "new-password" so managers don't autofill the user's saved
        // login into secret fields (connector creds, API keys, …). "off" won't
        // do it, browsers deliberately ignore autocomplete="off" on password
        // inputs. Login forms should override with "current-password".
        autoComplete="new-password"
        data-ph-no-capture
        leftChildren={
          isExistingValue ? (
            <>
              {leftChildren}
              <Tag icon={SvgKey} title={realValue} color="blue" size="md" />
            </>
          ) : (
            leftChildren
          )
        }
        rightChildren={
          // A field inside a <label> gets clicks under the label sent on to
          // the input. A click on a button's icon (not the button itself)
          // can still be sent on, so icons here take no pointer events and
          // every click lands on the button. Cancelling the click stops the
          // rest; cancelling mousedown keeps focus in the field.
          <div
            role="presentation"
            className="flex flex-row items-center gap-1 [&_svg]:pointer-events-none"
            onMouseDown={(e) => e.preventDefault()}
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
            }}
          >
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
              tooltipSide="start"
              tooltip={toggleLabel}
              aria-label={toggleLabel}
            />
            {rightChildren}
          </div>
        }
        {...props}
        placeholder={isExistingValue ? undefined : props.placeholder}
        // The input is empty while the tag shows, so a native required
        // check would block a form whose stored secret is unchanged.
        required={isExistingValue ? false : props.required}
      />
    </div>
  );
}

export { InputPasswordTypeIn, type InputPasswordTypeInProps };
