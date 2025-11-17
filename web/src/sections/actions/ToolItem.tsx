"use client";

import React from "react";
import { cn } from "@/lib/utils";
import Switch from "@/refresh-components/inputs/Switch";
import Text from "@/refresh-components/texts/Text";
import SvgAlertTriangle from "@/icons/alert-triangle";

export interface ToolItemProps {
  // Tool information
  name: string;
  description: string;
  icon?: React.ReactNode;

  // Tool state
  isAvailable: boolean;
  isEnabled?: boolean;

  // Handlers
  onToggle?: (enabled: boolean) => void;

  // Optional styling
  className?: string;
}

const ToolItem: React.FC<ToolItemProps> = ({
  name,
  description,
  icon,
  isAvailable,
  isEnabled = true,
  onToggle,
  className,
}) => {
  const unavailableStyles = !isAvailable
    ? "bg-background-neutral-02"
    : "bg-background-tint-00";

  const textOpacity = !isAvailable ? "opacity-50" : "";

  return (
    <div
      className={cn(
        "flex items-start justify-between w-full p-2 rounded-08 border border-border-01",
        unavailableStyles,
        className
      )}
    >
      {/* Left Section: Icon and Content */}
      <div className="flex gap-1 items-start flex-1 min-w-0 pr-2">
        {/* Icon Container */}
        {icon && (
          <div
            className={cn(
              "flex items-center justify-center p-0.5 shrink-0 w-5 h-5",
              textOpacity
            )}
          >
            {icon}
          </div>
        )}

        {/* Content Container */}
        <div className="flex flex-col items-start flex-1 min-w-0">
          {/* Tool Name */}
          <div className="flex items-center w-full min-h-[20px] px-0.5">
            <Text
              mainUiAction
              text04
              className={cn(textOpacity, !isAvailable && "line-through")}
            >
              {name}
            </Text>
          </div>

          {/* Description */}
          <div className="px-0.5 w-full">
            <Text
              text03
              secondaryBody
              className={cn("whitespace-pre-wrap", textOpacity)}
            >
              {description}
            </Text>
          </div>
        </div>
      </div>

      {/* Right Section: Status and Switch */}
      <div className="flex gap-2 items-start justify-end shrink-0">
        {/* Unavailable Badge */}
        {!isAvailable && (
          <div className="flex items-center min-h-[20px] px-0 py-0.5">
            <div className="flex gap-0.5 items-center">
              <div className="flex items-center px-0.5">
                <Text text03 secondaryBody className="text-right">
                  Tool unavailable
                </Text>
              </div>
              <div className="flex items-center justify-center p-0.5 w-4 h-4">
                <SvgAlertTriangle className="w-3 h-3 stroke-status-warning-05" />
              </div>
            </div>
          </div>
        )}

        {/* Switch */}
        <div className="flex items-center justify-center gap-1 h-5 px-0.5 py-0.5">
          <Switch
            checked={isEnabled}
            onCheckedChange={onToggle}
            disabled={!isAvailable}
          />
        </div>
      </div>
    </div>
  );
};

ToolItem.displayName = "ToolItem";
export default ToolItem;
