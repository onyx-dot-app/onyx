"use client";

import { type CSSProperties, type ReactNode } from "react";
import { cn } from "@opal/utils";

type CometTone = "info" | "success" | "error";

interface CometEdgeProps {
  children: ReactNode;
  /** Animate the traveling comet (live). */
  active?: boolean;
  /** Solid colored edge, no travel (a settled outcome). */
  settled?: boolean;
  tone?: CometTone;
  /** Seconds per lap; lower is faster. */
  speedSeconds?: number;
  /** px; match the wrapped card (rounded-08 = 8). */
  radius?: number;
  className?: string;
}

const TONE_VAR: Record<CometTone, string> = {
  info: "var(--status-info-05)",
  success: "var(--status-success-05)",
  error: "var(--status-error-05)",
};

const RECT_PROPS = {
  x: "0",
  y: "0",
  width: "100%",
  height: "100%",
  pathLength: 100,
} as const;

/**
 * Hairline comet on a card border — travels while `active`, then cross-fades
 * to a solid `tone` edge when `settled`. The comet is a full-size `<rect>`, so
 * it resizes with the card; `pathLength={100}` keeps the dash seamless.
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
              // Comet is always the live "working" color; tone is the settled edge.
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
            // Pause travel when hidden so it isn't animating at opacity 0.
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
