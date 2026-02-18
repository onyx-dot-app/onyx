"use client";

import { Button } from "@opal/components/buttons/Button/components";
import SvgEdit from "@opal/icons/edit";
import { useRef, useState } from "react";

import {
  SIZE_PRESETS,
  type ContentBaseProps,
  type SizePresetConfig,
} from "@opal/components/layouts/Content/presets";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type HeadingSizePreset = "headline" | "section";
type HeadingVariant = "heading" | "section";

interface HeadingLayoutProps extends ContentBaseProps {
  /** Size preset. Default: `"headline"`. */
  sizePreset?: HeadingSizePreset;

  /** Variant controls icon placement. `"heading"` = top, `"section"` = inline. Default: `"heading"`. */
  variant?: HeadingVariant;
}

// ---------------------------------------------------------------------------
// HeadingLayout
// ---------------------------------------------------------------------------

function HeadingLayout({
  sizePreset = "headline",
  variant = "heading",
  icon: Icon,
  title,
  description,
  editable,
  onTitleChange,
}: HeadingLayoutProps) {
  const [editing, setEditing] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const config: SizePresetConfig = SIZE_PRESETS[sizePreset];
  const iconPlacement = variant === "heading" ? "top" : "left";

  function commit() {
    if (!inputRef.current) return;
    const value = inputRef.current.value.trim();
    if (value && value !== title) onTitleChange?.(value);
    setEditing(false);
  }

  return (
    <div
      className="opal-content-heading"
      data-icon-placement={iconPlacement}
      style={{ gap: iconPlacement === "left" ? config.gap : undefined }}
    >
      {Icon && (
        <div
          className={`opal-content-heading-icon-container shrink-0 ${config.iconContainerPadding}`}
          style={{ minHeight: config.lineHeight }}
        >
          <Icon
            className="opal-content-heading-icon"
            style={{ width: config.iconSize, height: config.iconSize }}
          />
        </div>
      )}

      <div className="opal-content-heading-body">
        <div className="opal-content-heading-title-row">
          {editing ? (
            <input
              ref={inputRef}
              className={`opal-content-heading-input ${config.titleFont} text-text-04`}
              defaultValue={title}
              autoFocus
              onBlur={commit}
              onKeyDown={(e) => {
                if (e.key === "Enter") commit();
                if (e.key === "Escape") setEditing(false);
              }}
              style={{ height: config.lineHeight }}
            />
          ) : (
            <span
              className={`opal-content-heading-title ${
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
              className={`opal-content-heading-edit-button ${config.editButtonPadding}`}
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
        </div>

        {description && (
          <div className="opal-content-heading-description font-secondary-body text-text-03">
            {description}
          </div>
        )}
      </div>
    </div>
  );
}

export { HeadingLayout, type HeadingLayoutProps, type HeadingSizePreset };
