import { cn } from "@opal/utils";

export type ContextRingTone = "normal" | "warning" | "critical";

// Fill + track colors come from the Opal CSS-var palette (see web/CLAUDE.md
// §Colors) so dark mode and theming are handled automatically.
const TONE_FILL: Record<ContextRingTone, string> = {
  normal: "var(--theme-primary-05)",
  warning: "var(--status-warning-05)",
  critical: "var(--status-error-05)",
};
const TRACK_COLOR = "var(--background-neutral-03)";

export interface ContextRingProps {
  /** Filled portion of the ring, 0..1. */
  fraction: number;
  tone: ContextRingTone;
  ariaLabel: string;
  className?: string;
}

/** A small conic-gradient ring rendering a filled fraction. */
export default function ContextRing({
  fraction,
  tone,
  ariaLabel,
  className,
}: ContextRingProps) {
  const degrees = Math.min(1, Math.max(0, fraction)) * 360;
  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className={cn("size-4 shrink-0 rounded-full", className)}
      style={{
        background: `conic-gradient(${TONE_FILL[tone]} ${degrees}deg, ${TRACK_COLOR} 0deg)`,
      }}
    />
  );
}
