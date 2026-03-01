"use client";

import { Button } from "@opal/components/buttons/Button/components";
import type { SizeVariant } from "@opal/shared";
import SvgEdit from "@opal/icons/edit";
import type { IconFunctionComponent } from "@opal/types";
import { cn } from "@opal/utils";
import { useRef, useState } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ContentXlSizePreset = "headline" | "section";

interface ContentXlPresetConfig {
  /** Icon width/height (CSS value). */
  iconSize: string;
  /** Tailwind padding class for the icon container. */
  iconContainerPadding: string;
  /** More-icon-1 width/height (CSS value). */
  moreIcon1Size: string;
  /** Tailwind padding class for the more-icon-1 container. */
  moreIcon1ContainerPadding: string;
  /** More-icon-2 width/height (CSS value). */
  moreIcon2Size: string;
  /** Tailwind padding class for the more-icon-2 container. */
  moreIcon2ContainerPadding: string;
  /** Tailwind font class for the title. */
  titleFont: string;
  /** Title line-height — also used as icon container min-height (CSS value). */
  lineHeight: string;
  /** Button `size` prop for the edit button. Uses the shared `SizeVariant` scale. */
  editButtonSize: SizeVariant;
  /** Tailwind padding class for the edit button container. */
  editButtonPadding: string;
}

interface ContentXlProps {
  /** Optional icon component. */
  icon?: IconFunctionComponent;

  /** Main title text. */
  title: string;

  /** Optional description below the title. */
  description?: string;

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
}

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------

const CONTENT_XL_PRESETS: Record<ContentXlSizePreset, ContentXlPresetConfig> = {
  headline: {
    iconSize: "2rem",
    iconContainerPadding: "p-0.5",
    moreIcon1Size: "1rem",
    moreIcon1ContainerPadding: "p-0.5",
    moreIcon2Size: "2rem",
    moreIcon2ContainerPadding: "p-0.5",
    titleFont: "font-heading-h2",
    lineHeight: "2.25rem",
    editButtonSize: "md",
    editButtonPadding: "p-1",
  },
  section: {
    iconSize: "1.5rem",
    iconContainerPadding: "p-0.5",
    moreIcon1Size: "0.75rem",
    moreIcon1ContainerPadding: "p-0.5",
    moreIcon2Size: "1.5rem",
    moreIcon2ContainerPadding: "p-0.5",
    titleFont: "font-heading-h3",
    lineHeight: "1.75rem",
    editButtonSize: "sm",
    editButtonPadding: "p-0.5",
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
}: ContentXlProps) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(title);
  const inputRef = useRef<HTMLInputElement>(null);

  const config = CONTENT_XL_PRESETS[sizePreset];

  function startEditing() {
    setEditValue(title);
    setEditing(true);
  }

  function commit() {
    const value = editValue.trim();
    if (value && value !== title) onTitleChange?.(value);
    setEditing(false);
  }

  return (
    <div className="opal-content-xl">
      {(Icon || MoreIcon1 || MoreIcon2) && (
        <div className="opal-content-xl-icon-row">
          {Icon && (
            <div
              className={cn(
                "opal-content-xl-icon-container shrink-0",
                config.iconContainerPadding
              )}
              style={{ minHeight: config.lineHeight }}
            >
              <Icon
                className="opal-content-xl-icon"
                style={{ width: config.iconSize, height: config.iconSize }}
              />
            </div>
          )}

          {MoreIcon1 && (
            <div
              className={cn(
                "opal-content-xl-more-icon-container shrink-0",
                config.moreIcon1ContainerPadding
              )}
            >
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
            <div
              className={cn(
                "opal-content-xl-more-icon-container shrink-0",
                config.moreIcon2ContainerPadding
              )}
            >
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

      <div className="opal-content-xl-body">
        <div className="opal-content-xl-title-row">
          {editing ? (
            <div className="opal-content-xl-input-sizer">
              <span
                className={cn("opal-content-xl-input-mirror", config.titleFont)}
              >
                {editValue || "\u00A0"}
              </span>
              <input
                ref={inputRef}
                className={cn(
                  "opal-content-xl-input",
                  config.titleFont,
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
                    setEditValue(title);
                    setEditing(false);
                  }
                }}
                style={{ height: config.lineHeight }}
              />
            </div>
          ) : (
            <span
              className={cn(
                "opal-content-xl-title",
                config.titleFont,
                "text-text-04",
                editable && "cursor-pointer"
              )}
              onClick={editable ? startEditing : undefined}
              style={{ height: config.lineHeight }}
            >
              {title}
            </span>
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

        {description && (
          <div className="opal-content-xl-description font-secondary-body text-text-03">
            {description}
          </div>
        )}
      </div>
    </div>
  );
}

export { ContentXl, type ContentXlProps, type ContentXlSizePreset };
