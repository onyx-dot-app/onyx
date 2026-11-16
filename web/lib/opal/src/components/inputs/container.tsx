"use client";

import "@opal/components/inputs/shared.css";
import type React from "react";
import { IconContainer } from "@opal/components/icon-container/components";
import type { IconFunctionComponent, InputVariants } from "@opal/types";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// InputContainer
// ---------------------------------------------------------------------------

interface InputContainerProps extends Omit<
  React.HTMLAttributes<HTMLDivElement>,
  "onBlur"
> {
  ref?: React.Ref<HTMLDivElement>;
  /** Visual state; see `shared.css`. */
  variant?: InputVariants;
  /** The list the input opens is open: keeps the focused border. */
  open?: boolean;
  /** Grows with its content (rows, chips) from the 36px single line. */
  grows?: boolean;
  /**
   * The field a click on the chrome focuses. A click on an input or a
   * textarea inside keeps its own focus.
   */
  focusTarget?: (root: HTMLDivElement) => HTMLElement | null | undefined;
  /** Focus left the whole input, not a move between its parts. */
  onFieldBlur?: (event: React.FocusEvent<HTMLDivElement>) => void;
}

/**
 * The input chrome every Opal input shares (`.opal-input`): 36px with the
 * border, 6px inside the outer edge, 2px between its title line and its
 * trailing controls.
 */
function InputContainer({
  ref,
  variant = "primary",
  open = false,
  grows = false,
  focusTarget,
  onFieldBlur,
  className,
  onClick,
  children,
  ...rest
}: InputContainerProps) {
  return (
    <div
      ref={ref}
      role="presentation"
      {...rest}
      className={cn("opal-input", className)}
      data-variant={variant}
      data-open={open || undefined}
      data-grows={grows || undefined}
      onClick={(event) => {
        onClick?.(event);
        if (!focusTarget || event.defaultPrevented) return;
        if (
          event.target instanceof HTMLInputElement ||
          event.target instanceof HTMLTextAreaElement
        ) {
          return;
        }
        focusTarget(event.currentTarget)?.focus();
      }}
      onBlur={
        onFieldBlur &&
        ((event) => {
          if (event.currentTarget.contains(event.relatedTarget as Node | null))
            return;
          onFieldBlur(event);
        })
      }
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// InputTitleLine
// ---------------------------------------------------------------------------

interface InputTitleLineProps {
  /** Leading icon, in a 20px icon container. */
  icon?: IconFunctionComponent;
  /** `text-02` instead of the icon container's `text-03` (the search icon). */
  iconMuted?: boolean;
  /** Grows with wrapped content (chip rows), aligned to the top. */
  grows?: boolean;
  className?: string;
  /** The title: a text field, a label, or chips and a field. */
  children: React.ReactNode;
}

/**
 * An input's title line (`.opal-input-row`): 2px padding and a 4px gap
 * around the leading icon (20px) and the title (20px), one 24px row.
 */
function InputTitleLine({
  icon,
  iconMuted = false,
  grows = false,
  className,
  children,
}: InputTitleLineProps) {
  return (
    <div
      className={cn("opal-input-row", className)}
      data-grows={grows || undefined}
    >
      {icon && (
        <div
          className="opal-input-leading-icon"
          data-muted={iconMuted || undefined}
        >
          <IconContainer size="main-ui" icon={icon} />
        </div>
      )}
      {children}
    </div>
  );
}

export {
  InputContainer,
  InputTitleLine,
  type InputContainerProps,
  type InputTitleLineProps,
};
