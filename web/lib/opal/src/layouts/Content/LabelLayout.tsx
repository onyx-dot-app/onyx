"use client";

import { Button } from "@opal/components/buttons/Button/components";
import { Tag, type TagProps } from "@opal/components/Tag/components";
import type { InteractiveContainerHeightVariant } from "@opal/core";
import SvgAlertCircle from "@opal/icons/alert-circle";
import SvgAlertTriangle from "@opal/icons/alert-triangle";
import SvgEdit from "@opal/icons/edit";
import SvgXOctagon from "@opal/icons/x-octagon";
import type { IconFunctionComponent } from "@opal/types";
import { cn } from "@opal/utils";
import { useRef, useState } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type LabelSizePreset = "main-content" | "main-ui" | "secondary";

type LabelAuxIcon = "info-gray" | "info-blue" | "warning" | "error";

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
  /** Aux icon size = lineHeight − 2 × p-0.5. */
  auxIconSize: string;
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

  /** Auxiliary status icon rendered beside the title. */
  auxIcon?: LabelAuxIcon;

  /** Tag rendered beside the title. */
  tag?: TagProps;

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
    auxIconSize: "1.25rem",
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
    auxIconSize: "1rem",
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
    auxIconSize: "0.75rem",
  },
};

// ---------------------------------------------------------------------------
// LabelLayout
// ---------------------------------------------------------------------------

const AUX_ICON_CONFIG: Record<
  LabelAuxIcon,
  { icon: IconFunctionComponent; colorClass: string }
> = {
  "info-gray": { icon: SvgAlertCircle, colorClass: "text-text-02" },
  "info-blue": { icon: SvgAlertCircle, colorClass: "text-status-info-05" },
  warning: { icon: SvgAlertTriangle, colorClass: "text-status-warning-05" },
  error: { icon: SvgXOctagon, colorClass: "text-status-error-05" },
};

function LabelLayout({
  icon: Icon,
  title,
  description,
  editable,
  onTitleChange,
  optional,
  auxIcon,
  tag,
  sizePreset = "main-ui",
}: LabelLayoutProps) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(title);
  const inputRef = useRef<HTMLInputElement>(null);

  const config = LABEL_PRESETS[sizePreset];

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
    <div className="opal-content-label" style={{ gap: config.gap }}>
      {Icon && (
        <div
          className={cn(
            "opal-content-label-icon-container shrink-0",
            config.iconContainerPadding
          )}
          style={{ minHeight: config.lineHeight }}
        >
          <Icon
            className={cn("opal-content-label-icon", config.iconColorClass)}
            style={{ width: config.iconSize, height: config.iconSize }}
          />
        </div>
      )}

      <div className="opal-content-label-body">
        <div className="opal-content-label-title-row">
          {editing ? (
            <div className="opal-content-label-input-sizer">
              <span
                className={cn(
                  "opal-content-label-input-mirror",
                  config.titleFont
                )}
              >
                {editValue || "\u00A0"}
              </span>
              <input
                ref={inputRef}
                className={cn(
                  "opal-content-label-input",
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
                "opal-content-label-title",
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

          {optional && (
            <span
              className={cn(config.optionalFont, "text-text-03 shrink-0")}
              style={{ height: config.lineHeight }}
            >
              (Optional)
            </span>
          )}

          {auxIcon &&
            (() => {
              const { icon: AuxIcon, colorClass } = AUX_ICON_CONFIG[auxIcon];
              return (
                <div
                  className="opal-content-label-aux-icon shrink-0 p-0.5"
                  style={{ height: config.lineHeight }}
                >
                  <AuxIcon
                    className={colorClass}
                    style={{
                      width: config.auxIconSize,
                      height: config.auxIconSize,
                    }}
                  />
                </div>
              );
            })()}

          {tag && <Tag {...tag} />}

          {editable && !editing && (
            <div
              className={cn(
                "opal-content-label-edit-button",
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
          <div className="opal-content-label-description font-secondary-body text-text-03">
            {description}
          </div>
        )}
      </div>
    </div>
  );
}

export {
  LabelLayout,
  type LabelLayoutProps,
  type LabelSizePreset,
  type LabelAuxIcon,
};
