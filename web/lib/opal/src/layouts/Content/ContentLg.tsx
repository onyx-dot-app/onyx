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

type ContentLgSizePreset = "headline" | "section";

interface ContentLgPresetConfig {
  /** Icon width/height (CSS value). */
  iconSize: string;
  /** Tailwind padding class for the icon container. */
  iconContainerPadding: string;
  /** Gap between icon container and content (CSS value). */
  gap: string;
  /** Tailwind font class for the title. */
  titleFont: string;
  /** Title line-height — also used as icon container min-height (CSS value). */
  lineHeight: string;
  /** Button `size` prop for the edit button. Uses the shared `SizeVariant` scale. */
  editButtonSize: SizeVariant;
  /** Tailwind padding class for the edit button container. */
  editButtonPadding: string;
}

interface ContentLgProps {
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
  sizePreset?: ContentLgSizePreset;
}

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------

const CONTENT_LG_PRESETS: Record<ContentLgSizePreset, ContentLgPresetConfig> = {
  headline: {
    iconSize: "2rem",
    iconContainerPadding: "p-0.5",
    gap: "0.25rem",
    titleFont: "font-heading-h2",
    lineHeight: "2.25rem",
    editButtonSize: "md",
    editButtonPadding: "p-1",
  },
  section: {
    iconSize: "1.25rem",
    iconContainerPadding: "p-1",
    gap: "0rem",
    titleFont: "font-heading-h3-muted",
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
}: ContentLgProps) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(title);
  const inputRef = useRef<HTMLInputElement>(null);

  const config = CONTENT_LG_PRESETS[sizePreset];

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
    <div className="opal-content-lg" style={{ gap: config.gap }}>
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
                className={cn("opal-content-lg-input-mirror", config.titleFont)}
              >
                {editValue || "\u00A0"}
              </span>
              <input
                ref={inputRef}
                className={cn(
                  "opal-content-lg-input",
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
                "opal-content-lg-title",
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

        {description && (
          <div className="opal-content-lg-description font-secondary-body text-text-03">
            {description}
          </div>
        )}
      </div>
    </div>
  );
}

export { ContentLg, type ContentLgProps, type ContentLgSizePreset };
