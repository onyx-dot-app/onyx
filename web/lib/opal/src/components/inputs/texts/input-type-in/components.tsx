"use client";

import "@opal/components/inputs/texts/input-type-in/styles.css";
import { cn } from "@opal/utils";
import { SvgSearch, SvgX } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { Button } from "@opal/components";
import {
  InputContainer,
  InputTitleLine,
} from "@opal/components/inputs/container";
import { useOpalStrings } from "@opal/strings";
import type { InputVariants, WithoutStyles } from "@opal/types";

/**
 * Clears an input through the browser, so React sends its `onChange` a real
 * change event, as for typing.
 */
function clearNativeInput(input: HTMLInputElement) {
  Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value"
  )?.set?.call(input, "");
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

export interface InputTypeInProps extends WithoutStyles<
  Omit<React.InputHTMLAttributes<HTMLInputElement>, "disabled" | "readOnly">
> {
  ref?: React.Ref<HTMLInputElement>;
  variant?: InputVariants;
  /**
   * Leading icon. `"search"` shows the search icon and renders a native
   * `type="search"` field; a component shows that icon (a select's chosen
   * option icon).
   */
  icon?: "search" | IconFunctionComponent;
  /** Content before the text, after the leading icon (a chosen value shown as a tag). */
  leftChildren?: React.ReactNode;
  rightChildren?: React.ReactNode;
  /** Show the clear (×) button when the field has a value. */
  clearButton?: boolean;
  /**
   * Read-only regardless of `variant`, for a field that is only a trigger
   * (a select's button trigger). `variant="readOnly"` implies it.
   */
  readOnly?: boolean;
  /**
   * The list this field opens is open. The field keeps its focused border,
   * even when focus moves into the list.
   */
  open?: boolean;
}

/**
 * A styled text input with support for a leading icon,
 * a clear button, and an optional right section slot.
 *
 * @example
 * ```tsx
 * // Basic
 * <InputTypeIn value={value} onChange={(e) => setValue(e.target.value)} />
 *
 * // With search icon
 * <InputTypeIn icon="search" placeholder="Search..." value={q} onChange={...} />
 *
 * // Error state
 * <InputTypeIn variant="error" value={value} onChange={...} />
 *
 * // Read-only
 * <InputTypeIn variant="readOnly" value="Cannot edit" />
 *
 * // With clear button
 * <InputTypeIn clearButton value={q} onChange={...} />
 *
 * // With custom right content (e.g. password reveal) — suppresses clear button
 * <InputTypeIn
 *   value={password}
 *   onChange={...}
 *   rightChildren={<Button icon={SvgEye} onClick={toggle} />}
 * />
 * ```
 */
export default function InputTypeIn({
  ref,
  variant = "primary",
  leftChildren,
  icon: Icon,
  rightChildren,
  clearButton = false,
  readOnly = false,
  open = false,
  value,
  onChange,
  name,
  type = "text",
  ...props
}: InputTypeInProps) {
  const strings = useOpalStrings();
  const disabled = variant === "disabled";
  const isReadOnly = readOnly || variant === "readOnly";

  return (
    <InputContainer
      variant={variant}
      open={open}
      focusTarget={(root) => root.querySelector("input")}
      onKeyDown={(e) => {
        // Escape on a control beside the field (the clear button, a reveal
        // toggle, a chevron) returns focus to the field. It does so even when
        // a tooltip or popover consumed the key to close itself.
        if (e.key !== "Escape") return;
        const input = e.currentTarget.querySelector("input");
        if (input && e.target !== input) input.focus();
      }}
    >
      <InputTitleLine
        icon={Icon === "search" ? SvgSearch : Icon}
        iconMuted={Icon === "search"}
      >
        {leftChildren}

        <input
          ref={ref}
          // Chrome ignores autocomplete="off" when it guesses a text field takes
          // a saved card; it does not offer cards in search fields.
          type={Icon === "search" ? "search" : type}
          // dir="auto": typed text decides the direction so punctuation sits on the
          // correct side. While empty it inherits the page direction (see styles.css).
          dir="auto"
          name={name}
          disabled={disabled}
          readOnly={isReadOnly}
          value={value}
          onChange={onChange}
          className="opal-input-field"
          {...props}
        />
      </InputTitleLine>

      {clearButton && !rightChildren && !disabled && !isReadOnly && (
        <div className={cn(value === "" && "invisible")}>
          <Button
            icon={SvgX}
            aria-label={strings.clear}
            disabled={disabled}
            onClick={(event) => {
              event.stopPropagation();
              const input = event.currentTarget
                .closest(".opal-input")
                ?.querySelector("input");
              if (!input) return;
              clearNativeInput(input);
              // The button hides once the field is empty; keep focus in the
              // field rather than losing it to the page.
              input.focus();
            }}
            type="button"
            prominence="tertiary"
            size="sm"
            tooltip={strings.clear}
          />
        </div>
      )}

      {rightChildren}
    </InputContainer>
  );
}
