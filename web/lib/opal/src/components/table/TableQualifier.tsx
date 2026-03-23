"use client";

import React from "react";
import { cn } from "@opal/utils";
import { useTableSize } from "@opal/components/table/TableSizeContext";
import type { IconFunctionComponent } from "@opal/types";
import type { QualifierContentType } from "@opal/components/table/types";
import Checkbox from "@/refresh-components/inputs/Checkbox";

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
}

const iconSizes = {
  lg: 20,
  md: 16,
} as const;

function getOverlayStyles(selected: boolean, disabled: boolean) {
  if (disabled) {
    return selected ? "flex bg-action-link-00" : "hidden";
  }
  if (selected) {
    return "flex bg-action-link-00";
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
}: TableQualifierProps) {
  const resolvedSize = useTableSize();
  const iconSize = iconSizes[resolvedSize];
  const overlayStyles = getOverlayStyles(selected, disabled);

  function renderContent() {
    switch (content) {
      case "icon":
        return Icon ? <Icon size={iconSize} /> : null;

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
        resolvedSize === "lg" ? "h-9 w-9" : "h-7 w-7",
        disabled ? "cursor-not-allowed" : "cursor-default"
      )}
    >
      {showBackground ? (
        <div
          className={cn(
            "flex items-center justify-center overflow-hidden rounded-08 transition-colors",
            resolvedSize === "lg" ? "h-9 w-9" : "h-7 w-7",
            disabled
              ? "bg-background-neutral-03"
              : selected
                ? "bg-action-link-00"
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
          <Checkbox
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
