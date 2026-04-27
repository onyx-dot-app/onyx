"use client";

import { Button, Text } from "@opal/components";
import type { TextFont } from "@opal/components";
import type { ContainerSizeVariants } from "@opal/types";
import SvgEdit from "@opal/icons/edit";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { toPlainString } from "@opal/components/text/InlineMarkdown";
import { cn } from "@opal/utils";
import { useState } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ContentLgSizePreset = "headline" | "section";

interface ContentLgPresetConfig {
  /** Opal font name for the title. */
  titleFont: TextFont;
  /** Title line-height — also sets icon container height (CSS value). */
  lineHeight: string;
  /** Icon width/height = lineHeight - 4px (CSS value). */
  iconSize: string;
  /** Button `size` prop for the edit button. */
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
    titleFont: "heading-h2",
    lineHeight: "2.25rem",
    iconSize: "2rem",
    editButtonSize: "md",
    editButtonPadding: "p-1",
  },
  section: {
    titleFont: "heading-h3-muted",
    lineHeight: "1.75rem",
    iconSize: "1.5rem",
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
    <div ref={ref} className="opal-content-lg" data-opal-content>
      <div className="opal-content-lg-header">
        {Icon && (
          <div
            className="opal-content-lg-icon-container shrink-0"
            style={{ minHeight: config.lineHeight }}
          >
            <Icon
              className="opal-content-lg-icon"
              style={{ width: config.iconSize, height: config.iconSize }}
            />
          </div>
        )}

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
      </div>

      {description && toPlainString(description) && (
        <div
          className="opal-content-lg-description"
          style={
            Icon
              ? { paddingLeft: `calc(${config.lineHeight} + 0.125rem)` }
              : undefined
          }
        >
          <Text font="secondary-body" color="text-03" as="p">
            {description}
          </Text>
        </div>
      )}
    </div>
  );
}

export { ContentLg, type ContentLgProps, type ContentLgSizePreset };
