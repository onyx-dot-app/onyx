"use client";

import React from "react";
import { cn } from "@opal/utils";
import { useTableSize } from "@opal/components/table/TableSizeContext";
import type { IconFunctionComponent } from "@opal/types";
import type { QualifierContentType } from "@opal/components/table/types";
import { InputCheckbox } from "@opal/components";

interface TableQualifierProps {
  /** Content type displayed in the qualifier */
  content: QualifierContentType;
  /** Disables interaction */
  disabled?: boolean;
  /** Whether to show a selection checkbox overlay */
  selectable?: boolean;
  /** Whether the row is currently selected */
  selected?: boolean;
  /** Called when the checkbox is toggled */
  onSelectChange?: (selected: boolean) => void;
  /** Icon component to render (for "icon" content). */
  icon?: IconFunctionComponent;
  /** Image source URL (for "image" content). */
  imageSrc?: string;
  /** Image alt text (for "image" content). */
  imageAlt?: string;
  /** Show a tinted background container behind the content. */
  background?: boolean;
  /** The icon is an avatar: 28px or 24px by row height, instead of 16px. */
  avatar?: boolean;
}

// An icon is Opal's standard 16px at every row height; an avatar fills more
// of the tile, by row height.
const AVATAR_SIZES = { 2.75: 28, 2.25: 24 } as const;
const ICON_SIZE = 16;

function getOverlayStyles(selected: boolean, disabled: boolean) {
  if (disabled) {
    return selected ? "flex bg-action-selection-00" : "hidden";
  }
  if (selected) {
    return "flex bg-action-selection-00";
  }
  return "flex opacity-0 group-hover/row:opacity-100 group-focus-within/row:opacity-100 bg-background-tint-01";
}

function TableQualifier({
  content,
  disabled = false,
  selectable = false,
  selected = false,
  onSelectChange,
  icon: Icon,
  imageSrc,
  imageAlt = "",
  background = false,
  avatar = false,
}: TableQualifierProps) {
  const resolvedSize = useTableSize();
  const iconSize = avatar ? AVATAR_SIZES[resolvedSize] : ICON_SIZE;
  const overlayStyles = getOverlayStyles(selected, disabled);

  function renderContent() {
    switch (content) {
      case "icon":
        // shrink-0 and overflow-visible: a flex item may otherwise shrink the
        // SVG, and its own default overflow cuts a stroke at its edge. The
        // stroke is currentColor, so text-02 colors it.
        return Icon ? (
          <Icon
            size={iconSize}
            className="shrink-0 overflow-visible text-text-02"
          />
        ) : null;

      case "image":
        return imageSrc ? (
          <img
            src={imageSrc}
            alt={imageAlt}
            className="h-full w-full rounded-08 object-cover"
          />
        ) : null;

      case "simple":
      default:
        return null;
    }
  }

  const inner = renderContent();
  const showBackground = background && content !== "simple";

  return (
    <div
      className={cn(
        "group relative inline-flex shrink-0 items-center justify-center",
        resolvedSize === 2.75 ? "h-9 w-9" : "h-7 w-7",
        disabled ? "cursor-not-allowed" : "cursor-default"
      )}
    >
      {showBackground ? (
        <div
          className={cn(
            "flex items-center justify-center rounded-08 transition-colors",
            // Only an image needs the tile's corners clipped.
            content === "image" && "overflow-hidden",
            resolvedSize === 2.75 ? "h-9 w-9" : "h-7 w-7",
            disabled
              ? "bg-background-neutral-03"
              : selected
                ? "bg-action-selection-00"
                : "bg-background-tint-01"
          )}
        >
          {inner}
        </div>
      ) : (
        inner
      )}

      {/* Selection overlay */}
      {selectable && (
        <div
          className={cn(
            "absolute inset-0 items-center justify-center rounded-08",
            content === "simple" ? "flex" : overlayStyles
          )}
        >
          <InputCheckbox
            checked={selected}
            onCheckedChange={onSelectChange}
            disabled={disabled}
          />
        </div>
      )}
    </div>
  );
}

export default TableQualifier;
