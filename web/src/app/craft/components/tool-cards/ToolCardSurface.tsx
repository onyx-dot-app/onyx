"use client";

import type { ReactNode } from "react";
import { cn } from "@opal/utils";

interface ToolCardSurfaceProps {
  children: ReactNode;
  /** Apply the standard max-height + vertical scroll. @default true */
  scroll?: boolean;
  className?: string;
}

/**
 * ToolCardSurface - The shared bordered panel for every expandable tool-card
 * body (command output, file preview, search results, generic output, …).
 *
 * Top corners are squared (`rounded-b-08` only) so the body reads as an
 * extension of the card's trigger pill above it rather than a detached box.
 * Each body fills it with its own sections; use `ToolCardSection` for the
 * standard monospace padding and inter-section dividers.
 */
export default function ToolCardSurface({
  children,
  scroll = true,
  className,
}: ToolCardSurfaceProps) {
  return (
    <div
      className={cn(
        "rounded-b-08 border-[0.5px] border-border-01 overflow-hidden",
        "bg-background-neutral-01",
        scroll && "max-h-[18rem] overflow-y-auto",
        className
      )}
    >
      {children}
    </div>
  );
}

interface ToolCardSectionProps {
  children: ReactNode;
  /** Draw a top divider — use for every section after the first. */
  divider?: boolean;
  /** Subtle tint to visually separate (e.g. output below a command). */
  tinted?: boolean;
  className?: string;
}

/**
 * ToolCardSection - One padded region inside a `ToolCardSurface`. Sections
 * after the first should pass `divider` so the command and its result (or a
 * file and its footer) read as distinct bands.
 */
export function ToolCardSection({
  children,
  divider = false,
  tinted = false,
  className,
}: ToolCardSectionProps) {
  return (
    <div
      className={cn(
        "px-3 py-2",
        divider && "border-t-[0.5px] border-border-01",
        tinted && "bg-background-tint-00",
        className
      )}
    >
      {children}
    </div>
  );
}

/** Shared monospace style for code/command/output text (12px dm-mono). */
export const MONO_STYLE = {
  fontFamily: "var(--font-dm-mono)",
  fontSize: "12px",
} as const;
