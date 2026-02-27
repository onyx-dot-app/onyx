"use client";

import React from "react";
import { cn } from "@/lib/utils";
import { SvgUser } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import Text from "@/refresh-components/texts/Text";

interface TableQualifierProps {
  className?: string;
  /** Content type displayed in the qualifier */
  content: "icon" | "simple" | "image" | "avatar-icon" | "avatar-user";
  /** Size variant */
  size?: "regular" | "small";
  /** Disables interaction */
  disabled?: boolean;
  /** Whether to show a selection checkbox overlay */
  selectable?: boolean;
  /** Whether the row is currently selected */
  selected?: boolean;
  /** Called when the checkbox is toggled */
  onSelectChange?: (selected: boolean) => void;
  /** Icon component to render (for "icon" content type) */
  icon?: IconFunctionComponent;
  /** Image source URL (for "image" content type) */
  imageSrc?: string;
  /** Image alt text */
  imageAlt?: string;
  /** User initials (for "avatar-user" content type) */
  initials?: string;
}

const sizeClasses = {
  regular: "h-9 w-9",
  small: "h-7 w-7",
} as const;

const iconSizes = {
  regular: 16,
  small: 14,
} as const;

function getQualifierStyles(selected: boolean, disabled: boolean) {
  if (disabled) {
    return {
      container: "bg-background-neutral-03",
      icon: "stroke-text-02",
      overlay: selected ? "flex bg-action-link-00" : "hidden",
      overlayImage: selected ? "flex bg-mask-01 backdrop-blur-02" : "hidden",
    };
  }

  if (selected) {
    return {
      container: "bg-action-link-00",
      icon: "stroke-text-03",
      overlay: "flex bg-action-link-00",
      overlayImage: "flex bg-mask-01 backdrop-blur-02",
    };
  }

  return {
    container: "bg-background-tint-01",
    icon: "stroke-text-03",
    overlay: "hidden group-hover:flex bg-background-tint-01",
    overlayImage:
      "hidden group-hover:flex bg-mask-01 group-hover:backdrop-blur-02",
  };
}

function TableQualifier({
  className,
  content,
  size = "regular",
  disabled = false,
  selectable = false,
  selected = false,
  onSelectChange,
  icon: Icon,
  imageSrc,
  imageAlt = "",
  initials,
}: TableQualifierProps) {
  const isRound = content === "avatar-icon" || content === "avatar-user";
  const containerSize = sizeClasses[size];
  const iconSize = iconSizes[size];
  const styles = getQualifierStyles(selected, disabled);

  function renderContent() {
    switch (content) {
      case "icon":
        return Icon ? <Icon size={iconSize} className={styles.icon} /> : null;

      case "simple":
        return null;

      case "image":
        return imageSrc ? (
          <img
            src={imageSrc}
            alt={imageAlt}
            className={cn(
              "h-full w-full object-cover",
              isRound ? "rounded-full" : "rounded-08"
            )}
          />
        ) : null;

      case "avatar-icon":
        return <SvgUser size={iconSize} className={styles.icon} />;

      case "avatar-user":
        return (
          <div
            className={cn(
              "flex h-full w-full items-center justify-center rounded-full bg-text-05"
            )}
          >
            <Text
              figureSmallLabel
              textLight05
              className="select-none uppercase"
            >
              {initials}
            </Text>
          </div>
        );

      default:
        return null;
    }
  }

  return (
    <div
      className={cn(
        "group relative inline-flex shrink-0 items-center justify-center",
        containerSize,
        disabled ? "cursor-not-allowed" : "cursor-default",
        className
      )}
    >
      {/* Inner qualifier container */}
      <div
        className={cn(
          "flex items-center justify-center overflow-hidden transition-colors",
          containerSize,
          isRound ? "rounded-full" : "rounded-08",
          styles.container,
          content === "image" && disabled && !selected && "opacity-50"
        )}
      >
        {renderContent()}
      </div>

      {/* Selection overlay */}
      {selectable && (
        <div
          className={cn(
            "absolute inset-0 items-center justify-center",
            isRound ? "rounded-full" : "rounded-08",
            content === "simple"
              ? "flex"
              : content === "image"
                ? styles.overlayImage
                : styles.overlay
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
