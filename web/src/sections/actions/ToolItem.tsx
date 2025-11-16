"use client";

import React from "react";
import { cn } from "@/lib/utils";
import { Switch } from "@/components/ui/switch";
import Text from "@/refresh-components/texts/Text";

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
          <div className="flex items-center w-full min-h-[20px] px-0.5 relative">
            <Text mainUiAction text04 className={cn("relative", textOpacity)}>
              {name}
            </Text>

            {/* Strikethrough for unavailable items */}
            {!isAvailable && (
              <div className="absolute left-0.5 right-0.5 top-1/2 h-[1.5px] bg-text-02 -translate-y-1/2" />
            )}
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
                <svg
                  viewBox="0 0 12 12"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                  className="w-3 h-3"
                >
                  <path
                    d="M6 11C8.76142 11 11 8.76142 11 6C11 3.23858 8.76142 1 6 1C3.23858 1 1 3.23858 1 6C1 8.76142 3.23858 11 6 11Z"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <path
                    d="M6 3.5V6"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <circle cx="6" cy="8.5" r="0.5" fill="currentColor" />
                </svg>
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
            size="sm"
          />
        </div>
      </div>
    </div>
  );
};

ToolItem.displayName = "ToolItem";
export default ToolItem;
