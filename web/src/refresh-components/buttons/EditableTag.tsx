"use client";

import React from "react";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { SvgX } from "@opal/icons";
import type { IconProps } from "@opal/types";

export interface EditableTagProps {
  label: string;
  icon?: React.FunctionComponent<IconProps>;
  onRemove?: () => void;
  onClick?: () => void;
}

/**
 * EditableTag Component
 *
 * A removable tag component used for filters in CommandMenu and similar components.
 * Displays a label with optional icon and remove button.
 *
 * @example
 * ```tsx
 * // Basic usage with remove
 * <EditableTag
 *   label="Sessions"
 *   onRemove={() => removeFilter("sessions")}
 * />
 *
 * // With icon
 * <EditableTag
 *   label="Recent"
 *   icon={SvgClock}
 *   onRemove={() => removeFilter("recent")}
 * />
 *
 * // Clickable without remove
 * <EditableTag
 *   label="All"
 *   onClick={() => setFilter("all")}
 * />
 * ```
 */
export default function EditableTag({
  label,
  icon: Icon,
  onRemove,
  onClick,
}: EditableTagProps) {
  return (
    <div
      className={cn(
        "flex items-center gap-1 px-2 py-1 rounded-08",
        "bg-background-tint-01 hover:bg-background-tint-02",
        "transition-colors",
        onClick && "cursor-pointer"
      )}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
    >
      {Icon && <Icon className="w-[0.875rem] h-[0.875rem] stroke-text-03" />}
      <Text secondaryBody text03>
        {label}
      </Text>
      {onRemove && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="ml-0.5 hover:bg-background-tint-03 rounded-04 p-0.5 transition-colors"
          aria-label={`Remove ${label} filter`}
        >
          <SvgX className="w-[0.75rem] h-[0.75rem] stroke-text-02" />
        </button>
      )}
    </div>
  );
}
