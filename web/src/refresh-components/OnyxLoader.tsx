import React from "react";
import "./onyx-loader.css";

interface OnyxLoaderProps {
  /** Size of the animated mark, in pixels. Default: 64 (matches the design). */
  size?: number;
}

// Onyx mark geometry (16-unit viewBox), matching the @opal/icons `onyx-octagon`
// and `onyx-logo` paths. The stroke is defined here (rather than reusing those
// icon components) so its weight can be tuned: at the default 64px size it
// renders ~2.5px (Figma "Weight/Icon/Headline") and scales with `size`.
const STROKE_WIDTH = 0.625;

const OUTLINE_PATH =
  "M4.5 2.50002L8 1.00002L11.5 2.50002M13.5 4.50002L15 8.00001L13.5 11.5M11.5 13.5L8 15L4.5 13.5M2.5 11.5L1 8L2.5 4.50002";

const MARK_PATHS = [
  "M8 4.00001L4.5 2.50002L8 1.00002L11.5 2.50002L8 4.00001Z",
  "M8 12L11.5 13.5L8 15L4.5 13.5L8 12Z",
  "M4 8L2.5 11.5L1 8L2.5 4.50002L4 8Z",
  "M12 8.00002L13.5 4.50002L15 8.00001L13.5 11.5L12 8.00002Z",
];

/**
 * Onyx-branded loading mark.
 *
 * Renders the Onyx mark rotating a full turn while crossfading between the
 * octagon outline and the diamond logo (2s loop), per the Onyx UI Library
 * design. Both layers use `currentColor`, so the mark adapts to the
 * surrounding theme via `colors.css`.
 *
 * This is just the mark — for a full-page loading state with a "Loading …"
 * label, use `PageLoader`.
 */
export function OnyxLoader({ size = 64 }: OnyxLoaderProps) {
  return (
    <div
      role="status"
      aria-label="Loading"
      className="relative shrink-0 text-border-02"
      style={{ width: size, height: size }}
    >
      <div className="onyx-loader__rotator">
        <svg
          width={size}
          height={size}
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          xmlns="http://www.w3.org/2000/svg"
          className="onyx-loader__layer onyx-loader__outline"
        >
          <path
            d={OUTLINE_PATH}
            strokeWidth={STROKE_WIDTH}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <svg
          width={size}
          height={size}
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          xmlns="http://www.w3.org/2000/svg"
          className="onyx-loader__layer onyx-loader__mark"
        >
          {MARK_PATHS.map((d) => (
            <path
              key={d}
              d={d}
              strokeWidth={STROKE_WIDTH}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ))}
        </svg>
      </div>
    </div>
  );
}

export default OnyxLoader;
