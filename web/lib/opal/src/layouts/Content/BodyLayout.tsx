"use client";

import type { IconFunctionComponent } from "@opal/types";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type BodySizePreset = "main-content" | "main-ui" | "secondary";
type BodyOrientation = "vertical" | "inline" | "reverse";
type BodyProminence = "default" | "muted";

interface BodyPresetConfig {
  /** Icon width/height (CSS value). */
  iconSize: string;
  /** Tailwind padding class for the icon container. */
  iconContainerPadding: string;
  /** Tailwind font class for the title. */
  titleFont: string;
  /** Title line-height — also used as icon container min-height (CSS value). */
  lineHeight: string;
  /** Gap between icon container and title (CSS value). */
  gap: string;
}

/** Props for {@link BodyLayout}. Does not support editing or descriptions. */
interface BodyLayoutProps {
  /** Optional icon component. */
  icon?: IconFunctionComponent;

  /** Main title text (read-only — editing is not supported). */
  title: string;

  /** Size preset. Default: `"main-ui"`. */
  sizePreset?: BodySizePreset;

  /** Layout orientation. Default: `"inline"`. */
  orientation?: BodyOrientation;

  /** Title prominence. Default: `"default"`. */
  prominence?: BodyProminence;
}

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------

const BODY_PRESETS: Record<BodySizePreset, BodyPresetConfig> = {
  "main-content": {
    iconSize: "1rem",
    iconContainerPadding: "p-1",
    titleFont: "font-main-content-body",
    lineHeight: "1.5rem",
    gap: "0.125rem",
  },
  "main-ui": {
    iconSize: "1rem",
    iconContainerPadding: "p-0.5",
    titleFont: "font-main-ui-action",
    lineHeight: "1.25rem",
    gap: "0.25rem",
  },
  secondary: {
    iconSize: "0.75rem",
    iconContainerPadding: "p-0.5",
    titleFont: "font-secondary-action",
    lineHeight: "1rem",
    gap: "0.125rem",
  },
};

// ---------------------------------------------------------------------------
// BodyLayout
// ---------------------------------------------------------------------------

function BodyLayout({
  icon: Icon,
  title,
  sizePreset = "main-ui",
  orientation = "inline",
  prominence = "default",
}: BodyLayoutProps) {
  const config = BODY_PRESETS[sizePreset];
  const titleColorClass =
    prominence === "muted" ? "text-text-03" : "text-text-04";

  return (
    <div
      className="opal-content-body"
      data-orientation={orientation}
      style={{ gap: config.gap }}
    >
      {Icon && (
        <div
          className={cn(
            "opal-content-body-icon-container shrink-0",
            config.iconContainerPadding
          )}
          style={{ minHeight: config.lineHeight }}
        >
          <Icon
            className="opal-content-body-icon text-text-03"
            style={{ width: config.iconSize, height: config.iconSize }}
          />
        </div>
      )}

      <span
        className={cn(
          "opal-content-body-title",
          config.titleFont,
          titleColorClass
        )}
        style={{ height: config.lineHeight }}
      >
        {title}
      </span>
    </div>
  );
}

export {
  BodyLayout,
  type BodyLayoutProps,
  type BodySizePreset,
  type BodyOrientation,
  type BodyProminence,
};
