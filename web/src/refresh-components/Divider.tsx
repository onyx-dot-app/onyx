"use client";

import React from "react";
import { cn } from "@/lib/utils";
import { SvgChevronRight, SvgChevronDown, SvgInfoSmall } from "@opal/icons";
import Text from "@/refresh-components/texts/Text";
import type { IconProps } from "@opal/types";
import Truncated from "./texts/Truncated";

export interface DividerProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  /** Ref to the root element */
  ref?: React.Ref<HTMLDivElement>;
  /** Show title content instead of simple line */
  showTitle?: boolean;
  /** Title text */
  text?: string;
  /** Description text below title */
  description?: string;
  /** Show description */
  showDescription?: boolean;
  /** Enable foldable/collapsible behavior */
  foldable?: boolean;
  /** Controlled expanded state */
  expanded?: boolean;
  /** Callback when expanded changes */
  onClick?: () => void;
  /** Leading icon */
  icon?: React.FunctionComponent<IconProps>;
  /** Show info icon */
  showInfo?: boolean;
  /** Info text on right side */
  infoText?: string;
  /** Apply highlighted (hover) state styling */
  isHighlighted?: boolean;
  /** Show horizontal divider lines (default: true) */
  dividerLine?: boolean;
}

/**
 * Divider Component
 *
 * A flexible divider component that supports two modes:
 * 1. Simple horizontal line divider
 * 2. Title divider with optional foldable/collapsible behavior, icons, and multiple interactive states
 *
 * @example
 * ```tsx
 * // Simple horizontal line divider
 * <Divider />
 *
 * // Title divider
 * <Divider showTitle text="Section Title" />
 *
 * // Title divider with icon
 * <Divider showTitle text="Settings" icon={SvgSettings} />
 *
 * // Foldable divider (collapsed)
 * <Divider showTitle text="Details" foldable expanded={false} onClick={setExpanded} />
 *
 * // Foldable divider (expanded)
 * <Divider showTitle text="Details" foldable expanded onClick={setExpanded} />
 *
 * // With info icon and text
 * <Divider showTitle text="Section" showInfo infoText="3 items" />
 *
 * // With description
 * <Divider showTitle text="Title" description="Optional description" showDescription />
 * ```
 */
export default function Divider({
  ref,
  showTitle,
  text = "Title",
  description,
  showDescription,
  foldable,
  expanded,
  onClick,
  icon: Icon,
  showInfo,
  infoText,
  isHighlighted,
  dividerLine = true,
  className,
  ...props
}: DividerProps) {
  const handleClick = () => {
    if (foldable && onClick) {
      onClick();
    }
  };

  // Simple horizontal line divider
  if (!showTitle) {
    return (
      <div
        ref={ref}
        role="separator"
        className={cn("w-full py-1", className)}
        {...props}
      >
        <div className="h-px w-full bg-border-01" />
      </div>
    );
  }

  // Title divider with optional features
  return (
    <div
      ref={ref}
      role={foldable ? "button" : "separator"}
      aria-expanded={foldable ? expanded : undefined}
      tabIndex={foldable ? 0 : undefined}
      data-selected={isHighlighted ? "true" : undefined}
      onClick={foldable ? handleClick : undefined}
      onKeyDown={
        foldable
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                handleClick();
              }
            }
          : undefined
      }
      className={cn(
        "w-full mt-1 py-0.5 rounded-08",
        foldable && "group/divider cursor-pointer",
        foldable && !expanded && "hover:bg-background-tint-02",
        foldable && !expanded && isHighlighted && "bg-background-tint-02",
        foldable &&
          expanded &&
          "bg-background-tint-01 hover:bg-background-tint-02",
        className
      )}
      {...props}
    >
      {/* Title line */}
      <div
        className={cn(
          "flex items-center py-1",
          !dividerLine && (foldable ? "pl-1.5" : "px-2")
        )}
      >
        {/* Left divider line */}
        {dividerLine && (
          <div
            className={cn("h-px bg-border-01", foldable ? "w-1.5" : "w-2")}
          />
        )}

        {/* Content container */}
        <div className="flex items-center gap-0.5 px-0.5">
          {/* Icon container */}
          {Icon && (
            <div className="flex items-center justify-center size-5 p-0.5">
              <Icon
                className={cn(
                  "size-4 stroke-text-03",
                  foldable && "group-hover/divider:stroke-text-04",
                  foldable && expanded && "stroke-text-04",
                  foldable && isHighlighted && "stroke-text-04"
                )}
              />
            </div>
          )}

          {/* Title text */}
          <Text
            secondaryBody
            className={cn(
              "leading-4 truncate",
              !foldable && "text-text-03",
              foldable &&
                !expanded &&
                "text-text-03 group-hover/divider:text-text-04",
              foldable && expanded && "text-text-04",
              foldable && isHighlighted && "text-text-04"
            )}
          >
            {text}
          </Text>

          {/* Info icon */}
          {showInfo && (
            <div className="flex items-center justify-center size-5 p-0.5">
              <SvgInfoSmall
                className={cn(
                  "size-3 stroke-text-03",
                  foldable && "group-hover/divider:stroke-text-04",
                  foldable && expanded && "stroke-text-04",
                  foldable && isHighlighted && "stroke-text-04"
                )}
              />
            </div>
          )}
        </div>

        {/* Center divider line (flex-1 to fill remaining space) */}
        <div className={cn("flex-1", dividerLine && "h-px bg-border-01")} />

        {/* Info text on right side */}
        {infoText && (
          <>
            <Text
              secondaryBody
              className={cn(
                "leading-4 px-0.5",
                !foldable && "text-text-03",
                foldable &&
                  !expanded &&
                  "text-text-03 group-hover/divider:text-text-04",
                foldable && expanded && "text-text-04",
                foldable && isHighlighted && "text-text-04"
              )}
            >
              {infoText}
            </Text>
            {/* Right divider line after info text */}
            {dividerLine && (
              <div
                className={cn("h-px bg-border-01", foldable ? "w-1.5" : "w-2")}
              />
            )}
          </>
        )}

        {/* Chevron button for foldable */}
        {foldable && (
          <div className="flex items-center justify-center size-6">
            {expanded ? (
              <SvgChevronDown
                className={cn(
                  "size-4 stroke-text-03",
                  "group-hover/divider:stroke-text-04",
                  expanded && "stroke-text-04",
                  isHighlighted && "stroke-text-04"
                )}
              />
            ) : (
              <SvgChevronRight
                className={cn(
                  "size-4 stroke-text-03",
                  "group-hover/divider:stroke-text-04",
                  isHighlighted && "stroke-text-04"
                )}
              />
            )}
          </div>
        )}
      </div>

      {/* Description line */}
      {showDescription && description && (
        <div className="flex items-center py-1 pl-2">
          <Truncated secondaryBody text03>
            {description}
          </Truncated>
        </div>
      )}
    </div>
  );
}
