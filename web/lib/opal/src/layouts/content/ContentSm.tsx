"use client";

import type { IconFunctionComponent, RichStr } from "@opal/types";
import { Text, type TextFont } from "@opal/components/text/components";
import { toPlainString } from "@opal/components/text/InlineMarkdown";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ContentSmSizePreset = "main-content" | "main-ui" | "secondary";
type ContentSmOrientation = "vertical" | "inline" | "reverse";
type ContentSmProminence = "default" | "muted";

interface ContentSmPresetConfig {
  /** Icon width/height (CSS value). */
  iconSize: string;
  /** Tailwind padding class for the icon container. */
  iconContainerPadding: string;
  /** Font preset for the title. */
  titleFont: TextFont;
  /** Title line-height — also used as icon container min-height (CSS value). */
  lineHeight: string;
  /** Gap between icon container and title (CSS value). */
  gap: string;
}

/** Props for {@link ContentSm}. Does not support editing or descriptions. */
interface ContentSmProps {
  /** Optional icon component. */
  icon?: IconFunctionComponent;

  /** Main title text (read-only — editing is not supported). */
  title: string | RichStr;

  /** Size preset. Default: `"main-ui"`. */
  sizePreset?: ContentSmSizePreset;

  /** Layout orientation. Default: `"inline"`. */
  orientation?: ContentSmOrientation;

  /** Title prominence. Default: `"default"`. */
  prominence?: ContentSmProminence;

  /** Ref forwarded to the root `<div>`. */
  ref?: React.Ref<HTMLDivElement>;
}

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------

const CONTENT_SM_PRESETS: Record<ContentSmSizePreset, ContentSmPresetConfig> = {
  "main-content": {
    iconSize: "1rem",
    iconContainerPadding: "p-1",
    titleFont: "main-content-body",
    lineHeight: "1.5rem",
    gap: "0.125rem",
  },
  "main-ui": {
    iconSize: "1rem",
    iconContainerPadding: "p-0.5",
    titleFont: "main-ui-action",
    lineHeight: "1.25rem",
    gap: "0.25rem",
  },
  secondary: {
    iconSize: "0.75rem",
    iconContainerPadding: "p-0.5",
    titleFont: "secondary-action",
    lineHeight: "1rem",
    gap: "0.125rem",
  },
};

// ---------------------------------------------------------------------------
// ContentSm
// ---------------------------------------------------------------------------

function ContentSm({
  icon: Icon,
  title,
  sizePreset = "main-ui",
  orientation = "inline",
  prominence = "default",
  ref,
}: ContentSmProps) {
  const config = CONTENT_SM_PRESETS[sizePreset];

  return (
    <div
      ref={ref}
      className="opal-content-sm"
      data-orientation={orientation}
      data-prominence={prominence}
      style={{ gap: config.gap }}
    >
      {Icon && (
        <div
          className={cn(
            "opal-content-sm-icon-container shrink-0",
            config.iconContainerPadding
          )}
          style={{ minHeight: config.lineHeight }}
        >
          <Icon
            className="opal-content-sm-icon"
            style={{ width: config.iconSize, height: config.iconSize }}
          />
        </div>
      )}

      <Text
        font={config.titleFont}
        color="inherit"
        maxLines={1}
        title={toPlainString(title)}
      >
        {title}
      </Text>
    </div>
  );
}

export {
  ContentSm,
  type ContentSmProps,
  type ContentSmSizePreset,
  type ContentSmOrientation,
  type ContentSmProminence,
};
