"use client";

import React, { useState } from "react";
import type { IconProps } from "@opal/types";
import { cn, noProp } from "@/lib/utils";
import { Disabled } from "@opal/core";
import { Button, Text } from "@opal/components";
import SelectButton from "@/refresh-components/buttons/SelectButton";
import {
  SvgArrowExchange,
  SvgArrowRightCircle,
  SvgCheckSquare,
  SvgSettings,
  SvgUnplug,
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
  onDisconnect?: () => void;

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
  onDisconnect,
  connectLabel = "Connect",
  selectLabel = "Set as Default",
  selectedLabel = "Current Default",
  large = true,
  medium,
  className,
  disabled,
  ...rest
}: SelectProps) {
  const sizeClass = medium ? "h-[3.75rem]" : "min-h-[3.75rem] max-h-[5.25rem]";
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
    <Disabled disabled={disabled} allowClick>
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
            <Text font="main-ui-action" color="text-05">
              {title}
            </Text>
            <Text font="secondary-body" color="text-03">
              {description}
            </Text>
          </div>
        </div>

        {/* Right section - Actions */}
        <div className="flex flex-col h-full items-end justify-between gap-1">
          {/* Disconnected: Show Connect button */}
          {isDisconnected && (
            <Disabled disabled={disabled || !onConnect}>
              <Button
                prominence="tertiary"
                onClick={noProp(onConnect)}
                rightIcon={SvgArrowExchange}
              >
                {connectLabel}
              </Button>
            </Disabled>
          )}

          {/* Connected: Show select icon + settings icon */}
          {isConnected && (
            <>
              <Disabled disabled={disabled || !onSelect}>
                <SelectButton
                  action
                  folded
                  transient={isHovered}
                  onClick={onSelect}
                  rightIcon={SvgArrowRightCircle}
                >
                  {selectLabel}
                </SelectButton>
              </Disabled>
              <div className="flex px-1 gap-1">
                {onDisconnect && (
                  <Disabled disabled={disabled}>
                    <Button
                      icon={SvgUnplug}
                      tooltip="Disconnect"
                      prominence="tertiary"
                      size="sm"
                      onClick={noProp(onDisconnect)}
                      aria-label={`Disconnect ${title}`}
                    />
                  </Disabled>
                )}
                {onEdit && (
                  <Disabled disabled={disabled}>
                    <Button
                      icon={SvgSettings}
                      tooltip="Edit"
                      prominence="tertiary"
                      size="sm"
                      onClick={noProp(onEdit)}
                      aria-label={`Edit ${title}`}
                    />
                  </Disabled>
                )}
              </div>
            </>
          )}

          {/* Selected: Show "Current Default" label + settings icon */}
          {isSelected && (
            <>
              <Disabled disabled={disabled}>
                <SelectButton
                  action
                  engaged
                  onClick={onDeselect}
                  leftIcon={SvgCheckSquare}
                >
                  {selectedLabel}
                </SelectButton>
              </Disabled>
              <div className="flex px-1 gap-1">
                {onDisconnect && (
                  <Disabled disabled={disabled}>
                    <Button
                      icon={SvgUnplug}
                      tooltip="Disconnect"
                      prominence="tertiary"
                      size="sm"
                      onClick={noProp(onDisconnect)}
                      aria-label={`Disconnect ${title}`}
                    />
                  </Disabled>
                )}
                {onEdit && (
                  <Disabled disabled={disabled}>
                    <Button
                      icon={SvgSettings}
                      tooltip="Edit"
                      prominence="tertiary"
                      size="sm"
                      onClick={noProp(onEdit)}
                      aria-label={`Edit ${title}`}
                    />
                  </Disabled>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </Disabled>
  );
}
