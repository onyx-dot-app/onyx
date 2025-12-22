"use client";

import React from "react";
import type { IconProps } from "@opal/types";
import { cn, noProp } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";
import SelectButton from "@/refresh-components/buttons/SelectButton";
import {
  SvgArrowExchange,
  SvgArrowRightCircle,
  SvgCheckSquare,
  SvgSettings,
} from "@opal/icons";

export interface SelectProps {
  // Content
  icon: React.FunctionComponent<IconProps>;
  title: string;
  description: string;

  // State
  status: "disconnected" | "connected" | "selected";

  // Actions
  onConnect?: () => void;
  onSelect?: () => void;
  onDeselect?: () => void;
  onEdit?: () => void;

  // Labels (customizable)
  connectLabel?: string;
  selectLabel?: string;
  selectedLabel?: string;

  // Optional
  className?: string;
  disabled?: boolean;
}

export default function Select({
  icon: Icon,
  title,
  description,
  status,
  onConnect,
  onSelect,
  onDeselect,
  onEdit,
  connectLabel = "Connect",
  selectLabel = "Set as Default",
  selectedLabel = "Current Default",
  className,
  disabled,
}: SelectProps) {
  const isSelected = status === "selected";
  const isConnected = status === "connected";
  const isDisconnected = status === "disconnected";

  const isCardClickable = isDisconnected && onConnect && !disabled;

  const handleCardClick = () => {
    if (isCardClickable) {
      onConnect?.();
    }
  };

  return (
    <div
      onClick={isCardClickable ? handleCardClick : undefined}
      className={cn(
        "flex items-start justify-between gap-3 rounded-16 border p-4",
        isSelected
          ? "border-action-link-05 bg-action-link-01"
          : isConnected
            ? "border-border-01 bg-background-tint-00"
            : "border-border-01 bg-background-neutral-01",
        isCardClickable &&
          "cursor-pointer hover:bg-background-tint-01 transition-colors",
        disabled && "opacity-50 cursor-not-allowed",
        className
      )}
    >
      {/* Left section - Icon, Title, Description */}
      <div className="flex flex-1 items-start gap-1 py-1">
        <div className="flex size-5 items-center justify-center px-0.5 shrink-0">
          <Icon
            className={cn(
              "size-4",
              isSelected ? "text-action-text-link-05" : "text-text-02"
            )}
          />
        </div>
        <div className="flex flex-col gap-0.5">
          <Text mainUiAction text05>
            {title}
          </Text>
          <Text secondaryBody text03>
            {description}
          </Text>
        </div>
      </div>

      {/* Right section - Actions */}
      <div className="flex items-center justify-end gap-1">
        {/* Disconnected: Show Connect button */}
        {isDisconnected && (
          <Button
            action={false}
            tertiary
            disabled={disabled || !onConnect}
            onClick={noProp(onConnect)}
            rightIcon={SvgArrowExchange}
          >
            {connectLabel}
          </Button>
        )}

        {/* Connected: Show select icon + settings icon */}
        {isConnected && (
          <>
            <IconButton
              icon={SvgArrowRightCircle}
              tooltip={selectLabel}
              internal
              tertiary
              disabled={disabled || !onSelect}
              onClick={noProp(onSelect)}
              aria-label={selectLabel}
            />
            {onEdit && (
              <IconButton
                icon={SvgSettings}
                tooltip="Edit"
                internal
                tertiary
                onClick={noProp(onEdit)}
                aria-label={`Edit ${title}`}
              />
            )}
          </>
        )}

        {/* Selected: Show "Current Default" label + settings icon */}
        {isSelected && (
          <>
            <SelectButton
              action
              engaged
              disabled={disabled}
              leftIcon={SvgCheckSquare}
            >
              {selectedLabel}
            </SelectButton>
            {onEdit && (
              <IconButton
                icon={SvgSettings}
                tooltip="Edit"
                internal
                tertiary
                onClick={noProp(onEdit)}
                aria-label={`Edit ${title}`}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}
