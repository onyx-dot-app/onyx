"use client";

import type { IconFunctionComponent, RichStr } from "@opal/types";
import { Text } from "@opal/components";
import type { TextFont } from "@opal/components";
import { toPlainString } from "@opal/components/text/InlineMarkdown";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ContentSmSizePreset = "main-content" | "main-ui" | "secondary";
type ContentSmOrientation = "vertical" | "inline" | "reverse";

interface ContentSmPresetConfig {
  /** Opal font name for the title. */
  titleFont: TextFont;
  /** Title line-height — also sets icon container height (CSS value). */
  lineHeight: string;
  /** Icon width/height = lineHeight - 4px (CSS value). */
  iconSize: string;
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

  /** Ref forwarded to the root `<div>`. */
  ref?: React.Ref<HTMLDivElement>;
}

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------

const CONTENT_SM_PRESETS: Record<ContentSmSizePreset, ContentSmPresetConfig> = {
  "main-content": {
    titleFont: "main-content-body",
    lineHeight: "1.5rem",
    iconSize: "1.25rem",
  },
  "main-ui": {
    titleFont: "main-ui-body",
    lineHeight: "1.25rem",
    iconSize: "1rem",
  },
  secondary: {
    titleFont: "secondary-body",
    lineHeight: "1rem",
    iconSize: "0.75rem",
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
  ref,
}: ContentSmProps) {
  const config = CONTENT_SM_PRESETS[sizePreset];

  return (
    <div
      ref={ref}
      className="opal-content-sm"
      data-opal-content
      data-orientation={orientation}
    >
      {Icon && (
        <div
          className="opal-content-sm-icon-container shrink-0"
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
};
