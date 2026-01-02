"use client";

import React, { useState } from "react";
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

const containerClasses = {
  selected: "border-action-link-05 bg-action-link-01",
  connected: "border-border-01 bg-background-tint-00 hover:shadow-00",
  disconnected: "border-border-01 bg-background-neutral-01 hover:shadow-00",
} as const;

export interface SelectProps
  extends Omit<React.ComponentPropsWithoutRef<"div">, "title"> {
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

  // Size
  large?: boolean;
  medium?: boolean;

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
  large = true,
  medium,
  className,
  disabled,
  ...rest
}: SelectProps) {
  const sizeClass = medium ? "h-[3.75rem]" : "h-[4.25rem]";
  const containerClass = containerClasses[status];
  const [isHovered, setIsHovered] = useState(false);

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
      {...rest}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onClick={isCardClickable ? handleCardClick : undefined}
      className={cn(
        "flex items-start justify-between gap-3 rounded-16 border p-2 min-w-[17.5rem]",
        sizeClass,
        containerClass,
        isCardClickable &&
          "cursor-pointer hover:bg-background-tint-01 transition-colors",
        disabled && "opacity-50 cursor-not-allowed",
        className
      )}
    >
      {/* Left section - Icon, Title, Description */}
      <div className="flex flex-1 items-start gap-1 p-1">
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
            <SelectButton
              action
              folded
              transient={isHovered}
              disabled={disabled || !onSelect}
              onClick={onSelect}
              rightIcon={SvgArrowRightCircle}
            >
              {selectLabel}
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

        {/* Selected: Show "Current Default" label + settings icon */}
        {isSelected && (
          <>
            <SelectButton
              action
              engaged
              disabled={disabled}
              onClick={onDeselect}
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
