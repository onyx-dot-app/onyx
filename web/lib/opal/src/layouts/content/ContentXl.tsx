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

type ContentXlSizePreset = "headline" | "section";

interface ContentXlPresetConfig {
  /** Opal font name for the title. */
  titleFont: TextFont;
  /** Title line-height — also sets icon container height (CSS value). */
  lineHeight: string;
  /** Icon width/height = lineHeight - 4px (CSS value). */
  iconSize: string;
  /** More-icon-1 width/height (CSS value). */
  moreIcon1Size: string;
  /** More-icon-2 width/height (CSS value). */
  moreIcon2Size: string;
  /** Button `size` prop for the edit button. */
  editButtonSize: ContainerSizeVariants;
  /** Tailwind padding class for the edit button container. */
  editButtonPadding: string;
  /** Gap between icon row and title row (CSS value). */
  iconRowMarginBottom: string;
}

interface ContentXlProps {
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
  sizePreset?: ContentXlSizePreset;

  /** Optional secondary icon rendered in the icon row. */
  moreIcon1?: IconFunctionComponent;

  /** Optional tertiary icon rendered in the icon row. */
  moreIcon2?: IconFunctionComponent;

  /** Ref forwarded to the root `<div>`. */
  ref?: React.Ref<HTMLDivElement>;
}

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------

const CONTENT_XL_PRESETS: Record<ContentXlSizePreset, ContentXlPresetConfig> = {
  headline: {
    titleFont: "heading-h2",
    lineHeight: "2.25rem",
    iconSize: "2rem",
    moreIcon1Size: "1rem",
    moreIcon2Size: "2rem",
    editButtonSize: "md",
    editButtonPadding: "p-1",
    iconRowMarginBottom: "0rem",
  },
  section: {
    titleFont: "heading-h3",
    lineHeight: "1.75rem",
    iconSize: "1.5rem",
    moreIcon1Size: "0.75rem",
    moreIcon2Size: "1.5rem",
    editButtonSize: "sm",
    editButtonPadding: "p-0.5",
    iconRowMarginBottom: "0.25rem",
  },
};

// ---------------------------------------------------------------------------
// ContentXl
// ---------------------------------------------------------------------------

function ContentXl({
  sizePreset = "headline",
  icon: Icon,
  title,
  description,
  editable,
  onTitleChange,
  moreIcon1: MoreIcon1,
  moreIcon2: MoreIcon2,
  ref,
}: ContentXlProps) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(toPlainString(title));

  const config = CONTENT_XL_PRESETS[sizePreset];

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
    <div ref={ref} className="opal-content-xl" data-opal-content>
      {(Icon || MoreIcon1 || MoreIcon2) && (
        <div
          className="opal-content-xl-icon-row"
          style={{ marginBottom: config.iconRowMarginBottom }}
        >
          {Icon && (
            <div
              className="opal-content-xl-icon-container shrink-0"
              style={{ minHeight: config.lineHeight }}
            >
              <Icon
                className="opal-content-xl-icon"
                style={{ width: config.iconSize, height: config.iconSize }}
              />
            </div>
          )}

          {MoreIcon1 && (
            <div className="opal-content-xl-more-icon-container shrink-0">
              <MoreIcon1
                className="opal-content-xl-icon"
                style={{
                  width: config.moreIcon1Size,
                  height: config.moreIcon1Size,
                }}
              />
            </div>
          )}

          {MoreIcon2 && (
            <div className="opal-content-xl-more-icon-container shrink-0">
              <MoreIcon2
                className="opal-content-xl-icon"
                style={{
                  width: config.moreIcon2Size,
                  height: config.moreIcon2Size,
                }}
              />
            </div>
          )}
        </div>
      )}

      <div className="opal-content-xl-title-row">
        {editing ? (
          <div className="opal-content-xl-input-sizer">
            <span
              className={cn(
                "opal-content-xl-input-mirror",
                `font-${config.titleFont}`
              )}
            >
              {editValue || "\u00A0"}
            </span>
            <input
              className={cn(
                "opal-content-xl-input",
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
              "opal-content-xl-edit-button",
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
        <div className="opal-content-xl-description">
          <Text font="secondary-body" color="text-03" as="p">
            {description}
          </Text>
        </div>
      )}
    </div>
  );
}

export { ContentXl, type ContentXlProps, type ContentXlSizePreset };
