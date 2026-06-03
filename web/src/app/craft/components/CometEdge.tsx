"use client";

import { type CSSProperties, type ReactNode } from "react";
import { cn } from "@opal/utils";

type CometTone = "info" | "success" | "error";

interface CometEdgeProps {
  children: ReactNode;
  /** Animate a comet traveling the perimeter (live activity). */
  active?: boolean;
  /** Draw a solid colored edge with no travel (a settled outcome). */
  settled?: boolean;
  /** Edge color. @default "info" */
  tone?: CometTone;
  /** Seconds for one full lap — lower is faster. @default 3.6 */
  speedSeconds?: number;
  /** Corner radius in px; match the wrapped card (rounded-08 = 8). @default 8 */
  radius?: number;
  className?: string;
}

const TONE_VAR: Record<CometTone, string> = {
  info: "var(--status-info-05)",
  success: "var(--status-success-05)",
  error: "var(--status-error-05)",
};

// Geometry shared by both stacked strokes (full-bleed rounded rect).
const RECT_PROPS = {
  x: "0",
  y: "0",
  width: "100%",
  height: "100%",
  pathLength: 100,
} as const;

/**
 * CometEdge - Wraps a card and overlays a hairline "comet" that runs its
 * border. The comet is a single `<rect>` sized at 100% of the wrapper, so it
 * resizes natively with the card — no JS measurement — and stays smooth while
 * the card animates open/closed. `pathLength={100}` normalizes the dash so the
 * comet is one seamless segment at any size.
 *
 * Two strokes are always stacked when shown: the traveling comet (live,
 * info-blue) and a solid colored edge. Their opacities cross-fade between
 * `active` and `settled`, so a live approval visibly settles into a solid
 * green / red edge (`tone`) once it resolves.
 */
export default function CometEdge({
  children,
  active = false,
  settled = false,
  tone = "info",
  speedSeconds = 3.6,
  radius = 8,
  className,
}: CometEdgeProps) {
  const show = active || settled;

  return (
    <div className={cn("relative", className)} style={{ borderRadius: radius }}>
      {children}
      {show && (
        <svg
          aria-hidden
          className="pointer-events-none absolute inset-0 h-full w-full overflow-visible"
          style={
            {
              // Live comet is always the "working" color; the settle color is
              // the resolved outcome (success / error).
              "--comet-color": "var(--status-info-05)",
              "--comet-settle-color": TONE_VAR[tone],
              "--comet-speed": `${speedSeconds}s`,
            } as CSSProperties
          }
        >
          <rect
            {...RECT_PROPS}
            rx={radius}
            ry={radius}
            className="craft-comet"
            // Pause the travel when this stroke isn't the visible one (settled)
            // so it isn't animating invisibly at opacity 0.
            style={{
              opacity: active ? 1 : 0,
              animationPlayState: active ? "running" : "paused",
            }}
          />
          <rect
            {...RECT_PROPS}
            rx={radius}
            ry={radius}
            className="craft-comet-static"
            style={{ opacity: settled ? 1 : 0 }}
          />
        </svg>
      )}
    </div>
  );
}
