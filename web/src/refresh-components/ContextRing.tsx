import { cn } from "@opal/utils";
import { forwardRef, type HTMLAttributes } from "react";

export type ContextRingTone = "normal" | "warning" | "critical";

// Fill + track colors come from the Opal CSS-var palette (see web/CLAUDE.md
// §Colors) so dark mode and theming are handled automatically.
const TONE_FILL: Record<ContextRingTone, string> = {
  normal: "var(--theme-primary-05)",
  warning: "var(--status-warning-05)",
  critical: "var(--status-error-05)",
};
const TRACK_COLOR = "var(--background-neutral-03)";

export interface ContextRingProps extends HTMLAttributes<HTMLDivElement> {
  /** Filled portion of the ring, 0..1. */
  fraction: number;
  tone: ContextRingTone;
  ariaLabel: string;
  className?: string;
}

/** A small conic-gradient ring (donut) rendering a filled fraction. */
const ContextRing = forwardRef<HTMLDivElement, ContextRingProps>(
  function ContextRing({ fraction, tone, ariaLabel, className, ...rest }, ref) {
    const degrees = Math.min(1, Math.max(0, fraction)) * 360;
    return (
      <div
        ref={ref}
        role="img"
        aria-label={ariaLabel}
        // Focusable, and forwards ref + props so the wrapping Radix tooltip
        // (asChild) can attach its hover/focus handlers — without this the
        // tooltip never triggers.
        tabIndex={0}
        className={cn("size-4 shrink-0 rounded-full", className)}
        style={{
          background: `conic-gradient(${TONE_FILL[tone]} ${degrees}deg, ${TRACK_COLOR} 0deg)`,
          // Punch out the center so it reads as a ring (donut), not a filled pie.
          WebkitMask: "radial-gradient(closest-side, transparent 58%, #000 60%)",
          mask: "radial-gradient(closest-side, transparent 58%, #000 60%)",
        }}
        {...rest}
      />
    );
  },
);

export default ContextRing;
