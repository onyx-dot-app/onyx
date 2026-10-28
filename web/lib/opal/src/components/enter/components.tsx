"use client";

import "@opal/components/enter/styles.css";
import React from "react";
import { cn } from "@opal/utils";
import type { ExtremaSizeVariants, WithoutStyles } from "@opal/types";
import { heightVariants, widthVariants } from "@opal/shared";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * How the content arrives. `fade-up`: fades in while rising 8px.
 * `fade-from-end` / `fade-from-start`: fades in while moving 8px from the
 * inline end / start (mirrored in right-to-left text).
 */
type EnterVariant = "fade-up" | "fade-from-end" | "fade-from-start";

type EnterProps = WithoutStyles<React.HTMLAttributes<HTMLDivElement>> & {
  children: React.ReactNode;
  /** @default "fade-up" */
  variant?: EnterVariant;
  /**
   * Open the height from zero first, then play `variant`, so the content
   * makes room before it arrives. @default false
   */
  grow?: boolean;
  /** Width preset. @default "full" */
  width?: ExtremaSizeVariants;
  /** Height preset. When omitted, no height class is applied. */
  height?: ExtremaSizeVariants;
  /** Ref forwarded to the root `<div>`. */
  ref?: React.Ref<HTMLDivElement>;
};

// ---------------------------------------------------------------------------
// Enter
// ---------------------------------------------------------------------------

/**
 * Animates its content in once, when it mounts. Change the `key` to play it
 * again, e.g. on each route or view change.
 *
 * @example
 * ```tsx
 * <Enter key={pathname} height="full">
 *   {page}
 * </Enter>
 * ```
 */
function Enter({
  children,
  variant = "fade-up",
  grow = false,
  width = "full",
  height,
  ref,
  ...props
}: EnterProps) {
  const rootClassName = cn(
    "opal-enter",
    widthVariants[width],
    height && heightVariants[height]
  );

  if (!grow) {
    return (
      <div
        {...props}
        ref={ref}
        className={cn(rootClassName, "opal-enter-motion")}
        data-enter-variant={variant}
      >
        {children}
      </div>
    );
  }

  // The root opens the height; the inner element plays the variant after it.
  return (
    <div {...props} ref={ref} className={rootClassName} data-enter-grow="">
      <div className="opal-enter-motion" data-enter-variant={variant}>
        {children}
      </div>
    </div>
  );
}

export { Enter, type EnterProps, type EnterVariant };
