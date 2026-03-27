"use client";

import { Button } from "@opal/components/buttons/button/components";
import type { ContainerSizeVariants } from "@opal/types";
import SvgEdit from "@opal/icons/edit";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { Text, type TextFont } from "@opal/components/text/components";
import { toPlainString } from "@opal/components/text/InlineMarkdown";
import { cn } from "@opal/utils";
import { useState } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ContentLgSizePreset = "headline" | "section";

interface ContentLgPresetConfig {
  /** Icon width/height (CSS value). */
  iconSize: string;
  /** Tailwind padding class for the icon container. */
  iconContainerPadding: string;
  /** Gap between icon container and content (CSS value). */
  gap: string;
  /** Opal font name for the title (without `font-` prefix). */
  titleFont: TextFont;
  /** Title line-height — also used as icon container min-height (CSS value). */
  lineHeight: string;
  /** Button `size` prop for the edit button. Uses the shared `SizeVariant` scale. */
  editButtonSize: ContainerSizeVariants;
  /** Tailwind padding class for the edit button container. */
  editButtonPadding: string;
}

interface ContentLgProps {
  /** Optional icon component. */
  icon?: IconFunctionComponent;

  /** Main title text. */
  title: string | RichStr;

  /** Optional description below the title. */
  description?: string | RichStr;

  /** Enable inline editing of the title. */
  editable?: boolean;

  /** Called when the user commits an edit. */
  onTitleChange?: (newTitle: string) => void;

  /** Size preset. Default: `"headline"`. */
  sizePreset?: ContentLgSizePreset;

  /** Ref forwarded to the root `<div>`. */
  ref?: React.Ref<HTMLDivElement>;
}

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------

const CONTENT_LG_PRESETS: Record<ContentLgSizePreset, ContentLgPresetConfig> = {
  headline: {
    iconSize: "2rem",
    iconContainerPadding: "p-0.5",
    gap: "0.25rem",
    titleFont: "heading-h2",
    lineHeight: "2.25rem",
    editButtonSize: "md",
    editButtonPadding: "p-1",
  },
  section: {
    iconSize: "1.25rem",
    iconContainerPadding: "p-1",
    gap: "0rem",
    titleFont: "heading-h3-muted",
    lineHeight: "1.75rem",
    editButtonSize: "sm",
    editButtonPadding: "p-0.5",
  },
};

// ---------------------------------------------------------------------------
// ContentLg
// ---------------------------------------------------------------------------

function ContentLg({
  sizePreset = "headline",
  icon: Icon,
  title,
  description,
  editable,
  onTitleChange,
  ref,
}: ContentLgProps) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(toPlainString(title));

  const config = CONTENT_LG_PRESETS[sizePreset];

  function startEditing() {
    setEditValue(toPlainString(title));
    setEditing(true);
  }

  function commit() {
    const value = editValue.trim();
    if (value && value !== toPlainString(title)) onTitleChange?.(value);
    setEditing(false);
  }

  return (
    <div ref={ref} className="opal-content-lg" style={{ gap: config.gap }}>
      {Icon && (
        <div
          className={cn(
            "opal-content-lg-icon-container shrink-0",
            config.iconContainerPadding
          )}
          style={{ minHeight: config.lineHeight }}
        >
          <Icon
            className="opal-content-lg-icon"
            style={{ width: config.iconSize, height: config.iconSize }}
          />
        </div>
      )}

      <div className="opal-content-lg-body">
        <div className="opal-content-lg-title-row">
          {editing ? (
            <div className="opal-content-lg-input-sizer">
              <span
                className={cn(
                  "opal-content-lg-input-mirror",
                  `font-${config.titleFont}`
                )}
              >
                {editValue || "\u00A0"}
              </span>
              <input
                className={cn(
                  "opal-content-lg-input",
                  `font-${config.titleFont}`,
                  "text-text-04"
                )}
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                size={1}
                autoFocus
                onFocus={(e) => e.currentTarget.select()}
                onBlur={commit}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commit();
                  if (e.key === "Escape") {
                    setEditValue(toPlainString(title));
                    setEditing(false);
                  }
                }}
                style={{ height: config.lineHeight }}
              />
            </div>
          ) : (
            <Text
              font={config.titleFont}
              color="inherit"
              maxLines={1}
              title={toPlainString(title)}
              onClick={editable ? startEditing : undefined}
            >
              {title}
            </Text>
          )}

          {editable && !editing && (
            <div
              className={cn(
                "opal-content-lg-edit-button",
                config.editButtonPadding
              )}
            >
              <Button
                icon={SvgEdit}
                prominence="internal"
                size={config.editButtonSize}
                tooltip="Edit"
                tooltipSide="right"
                onClick={startEditing}
              />
            </div>
          )}
        </div>

        {description && toPlainString(description) && (
          <div className="opal-content-lg-description">
            <Text font="secondary-body" color="text-03" as="p">
              {description}
            </Text>
          </div>
        )}
      </div>
    </div>
  );
}

export { ContentLg, type ContentLgProps, type ContentLgSizePreset };
