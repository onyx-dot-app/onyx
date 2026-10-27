"use client";

import "@opal/components/enter/styles.css";
import React from "react";
import { cn } from "@opal/utils";
import type { ExtremaSizeVariants, WithoutStyles } from "@opal/types";
import { heightVariants, widthVariants } from "@opal/shared";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** How the content arrives. `fade-up`: fades in while rising 8px. */
type EnterVariant = "fade-up";

type EnterProps = WithoutStyles<React.HTMLAttributes<HTMLDivElement>> & {
  children: React.ReactNode;
  /** @default "fade-up" */
  variant?: EnterVariant;
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
  width = "full",
  height,
  ref,
  ...props
}: EnterProps) {
  return (
    <div
      {...props}
      ref={ref}
      className={cn(
        "opal-enter",
        widthVariants[width],
        height && heightVariants[height]
      )}
      data-enter-variant={variant}
    >
      {children}
    </div>
  );
}

export { Enter, type EnterProps, type EnterVariant };
