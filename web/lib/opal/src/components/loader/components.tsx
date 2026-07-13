import "@opal/components/loader/styles.css";
import { cn } from "@opal/utils";
import type { IconFunctionComponent } from "@opal/types";
import { SvgLoader } from "@opal/icons";

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------

// The mark renders in `currentColor`, so color is set as a text token on the
// wrapper. Default is the neutral `border-02`; pass `color` to override.
const COLOR_CLASS = {
  "border-02": "text-border-02",
  "text-02": "text-text-02",
  "text-03": "text-text-03",
  "text-04": "text-text-04",
  "text-05": "text-text-05",
  "status-error-05": "text-status-error-05",
  "status-success-05": "text-status-success-05",
  "status-warning-05": "text-status-warning-05",
} as const;

type LoaderColor = keyof typeof COLOR_CLASS;

// ---------------------------------------------------------------------------
// IconLoader
// ---------------------------------------------------------------------------

interface IconLoaderProps {
  /** Icon to spin. @default the generic `SvgLoader` spinner */
  icon?: IconFunctionComponent;

  /** Size of the icon, in pixels. @default 24 */
  size?: number;

  /** Mark color token. @default "border-02" */
  color?: LoaderColor;
}

/**
 * Generic loader: continuously spins the given icon. Pass any `@opal/icons`
 * icon, or use the default spinner. Holds still under `prefers-reduced-motion`.
 * For the Onyx-branded octagon mark, use `OnyxLoader`.
 */
function IconLoader({
  icon: Icon = SvgLoader,
  size = 24,
  color = "border-02",
}: IconLoaderProps) {
  return (
    <Icon
      size={size}
      role="status"
      aria-label="Loading"
      className={cn("shrink-0 motion-safe:animate-spin", COLOR_CLASS[color])}
    />
  );
}

// ---------------------------------------------------------------------------
// OnyxLoader
// ---------------------------------------------------------------------------

interface OnyxLoaderProps {
  /** Size of the animated mark, in pixels. @default 64 */
  size?: number;

  /** Mark color token. @default "border-02" */
  color?: LoaderColor;
}

// Onyx mark geometry (16-unit viewBox), matching the @opal/icons
// `onyx-octagon` and `onyx-logo` paths. The stroke is defined here rather
// than reusing those icon components so its weight can be tuned: at the
// default 64px it renders ~2.5px and scales with `size`.
const STROKE_WIDTH = 0.625;

const OUTLINE_PATH =
  "M4.5 2.50002L8 1.00002L11.5 2.50002M13.5 4.50002L15 8.00001L13.5 11.5M11.5 13.5L8 15L4.5 13.5M2.5 11.5L1 8L2.5 4.50002";

function svgLayerProps(size: number) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 16 16",
    fill: "none",
    stroke: "currentColor",
    xmlns: "http://www.w3.org/2000/svg",
  };
}

const MARK_PATHS = [
  "M8 4.00001L4.5 2.50002L8 1.00002L11.5 2.50002L8 4.00001Z",
  "M8 12L11.5 13.5L8 15L4.5 13.5L8 12Z",
  "M4 8L2.5 11.5L1 8L2.5 4.50002L4 8Z",
  "M12 8.00002L13.5 4.50002L15 8.00001L13.5 11.5L12 8.00002Z",
];

/**
 * Onyx-branded loading mark: rotates a full turn while crossfading between
 * the octagon outline and the diamond logo (2s loop). Both layers use
 * `currentColor`, so the mark adapts to the surrounding theme. For a
 * full-page loading state with a label, use `PageLoader`.
 */
function OnyxLoader({ size = 64, color = "border-02" }: OnyxLoaderProps) {
  return (
    <div
      role="status"
      aria-label="Loading"
      className={cn("relative shrink-0", COLOR_CLASS[color])}
      style={{ width: size, height: size }}
    >
      <div className="opal-loader-rotator">
        <svg
          {...svgLayerProps(size)}
          className="opal-loader-layer opal-loader-outline"
        >
          <path
            d={OUTLINE_PATH}
            strokeWidth={STROKE_WIDTH}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <svg
          {...svgLayerProps(size)}
          className="opal-loader-layer opal-loader-mark"
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

export {
  IconLoader,
  type IconLoaderProps,
  OnyxLoader,
  type OnyxLoaderProps,
  type LoaderColor,
};
