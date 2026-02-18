"use client";

import { Button } from "@opal/components/buttons/Button/components";
import type { InteractiveContainerHeightVariant } from "@opal/core";
import SvgEdit from "@opal/icons/edit";
import type { IconFunctionComponent } from "@opal/types";
import { useRef, useState } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type LabelSizePreset = "main-content" | "main-ui" | "secondary";

interface LabelPresetConfig {
  iconSize: string;
  iconContainerPadding: string;
  iconColorClass: string;
  titleFont: string;
  lineHeight: string;
  gap: string;
  editButtonSize: InteractiveContainerHeightVariant;
  editButtonPadding: string;
  optionalFont: string;
}

interface LabelLayoutProps {
  /** Optional icon component. */
  icon?: IconFunctionComponent;

  /** Main title text. */
  title: string;

  /** Optional description text below the title. */
  description?: string;

  /** Enable inline editing of the title. */
  editable?: boolean;

  /** Called when the user commits an edit. */
  onTitleChange?: (newTitle: string) => void;

  /** When `true`, renders "(Optional)" beside the title. */
  optional?: boolean;

  /** Size preset. Default: `"main-ui"`. */
  sizePreset?: LabelSizePreset;
}

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------

const LABEL_PRESETS: Record<LabelSizePreset, LabelPresetConfig> = {
  "main-content": {
    iconSize: "1rem",
    iconContainerPadding: "p-1",
    iconColorClass: "text-text-04",
    titleFont: "font-main-content-emphasis",
    lineHeight: "1.5rem",
    gap: "0.125rem",
    editButtonSize: "sm",
    editButtonPadding: "p-0",
    optionalFont: "font-main-content-muted",
  },
  "main-ui": {
    iconSize: "1rem",
    iconContainerPadding: "p-0.5",
    iconColorClass: "text-text-03",
    titleFont: "font-main-ui-action",
    lineHeight: "1.25rem",
    gap: "0.25rem",
    editButtonSize: "xs",
    editButtonPadding: "p-0",
    optionalFont: "font-main-ui-muted",
  },
  secondary: {
    iconSize: "0.75rem",
    iconContainerPadding: "p-0.5",
    iconColorClass: "text-text-04",
    titleFont: "font-secondary-action",
    lineHeight: "1rem",
    gap: "0.125rem",
    editButtonSize: "2xs",
    editButtonPadding: "p-0",
    optionalFont: "font-secondary-action",
  },
};

// ---------------------------------------------------------------------------
// LabelLayout
// ---------------------------------------------------------------------------

function LabelLayout({
  icon: Icon,
  title,
  description,
  editable,
  onTitleChange,
  optional,
  sizePreset = "main-ui",
}: LabelLayoutProps) {
  const [editing, setEditing] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const config = LABEL_PRESETS[sizePreset];

  function commit() {
    if (!inputRef.current) return;
    const value = inputRef.current.value.trim();
    if (value && value !== title) onTitleChange?.(value);
    setEditing(false);
  }

  return (
    <div className="opal-content-label" style={{ gap: config.gap }}>
      {Icon && (
        <div
          className={`opal-content-label-icon-container shrink-0 ${config.iconContainerPadding}`}
          style={{ minHeight: config.lineHeight }}
        >
          <Icon
            className={`opal-content-label-icon ${config.iconColorClass}`}
            style={{ width: config.iconSize, height: config.iconSize }}
          />
        </div>
      )}

      <div className="opal-content-label-body">
        <div className="opal-content-label-title-row">
          {editing ? (
            <input
              ref={inputRef}
              className={`opal-content-label-input ${config.titleFont} text-text-04`}
              defaultValue={title}
              autoFocus
              onFocus={(e) => e.currentTarget.select()}
              onBlur={commit}
              onKeyDown={(e) => {
                if (e.key === "Enter") commit();
                if (e.key === "Escape") setEditing(false);
              }}
              style={{ height: config.lineHeight }}
            />
          ) : (
            <span
              className={`opal-content-label-title ${
                config.titleFont
              } text-text-04${editable ? " cursor-pointer" : ""}`}
              onClick={editable ? () => setEditing(true) : undefined}
              style={{ height: config.lineHeight }}
            >
              {title}
            </span>
          )}

          {editable && !editing && (
            <div
              className={`opal-content-label-edit-button ${config.editButtonPadding}`}
            >
              <Button
                icon={SvgEdit}
                prominence="internal"
                size={config.editButtonSize}
                tooltip="Edit"
                tooltipSide="right"
                onClick={() => setEditing(true)}
              />
            </div>
          )}

          {optional && (
            <span
              className={`${config.optionalFont} text-text-03 shrink-0`}
              style={{ height: config.lineHeight }}
            >
              (Optional)
            </span>
          )}
        </div>

        {description && (
          <div className="opal-content-label-description font-secondary-body text-text-03">
            {description}
          </div>
        )}
      </div>
    </div>
  );
}

export { LabelLayout, type LabelLayoutProps, type LabelSizePreset };
