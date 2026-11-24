"use client";

import "@opal/components/buttons/avatar-button/styles.css";
import { forwardRef } from "react";
import { SvgEdit } from "@opal/icons";
import { cn } from "@opal/utils";

type AvatarButtonProps = Omit<
  React.ButtonHTMLAttributes<HTMLButtonElement>,
  "type" | "children" | "aria-label"
> & {
  /** The button's accessible name. The avatar inside is decorative. */
  "aria-label": string;
  /** Diameter in pixels. */
  size: number;
  /** The avatar, drawn at `size`. */
  children: React.ReactNode;
  /** A save is running. The button looks disabled but keeps focus; the caller
   * ignores clicks meanwhile. */
  busy?: boolean;
};

/** A round button around an avatar. Hover and keyboard focus show a gray
 * overlay with a pencil. It spreads its props and forwards its ref, so it can
 * be a `Dropdown.Trigger asChild`. */
const AvatarButton = forwardRef<HTMLButtonElement, AvatarButtonProps>(
  function AvatarButton(
    { size, children, busy, className, style, ...props },
    ref
  ) {
    return (
      <button
        ref={ref}
        type="button"
        aria-disabled={busy || undefined}
        aria-busy={busy || undefined}
        {...props}
        className={cn("opal-avatar-button", className)}
        style={{
          width: `${size / 16}rem`,
          height: `${size / 16}rem`,
          ...style,
        }}
      >
        {children}
        <span className="opal-avatar-button-overlay" aria-hidden>
          <SvgEdit />
        </span>
      </button>
    );
  }
);

export { AvatarButton, type AvatarButtonProps };
