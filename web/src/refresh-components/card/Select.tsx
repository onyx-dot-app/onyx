"use client";

import React, { useState } from "react";
import type { IconProps } from "@opal/types";
import { cn, noProp } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";
import {
  SvgArrowExchange,
  SvgArrowRightCircle,
  SvgCheckSquare,
  SvgX,
  SvgEdit,
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

interface HoverButtonProps extends React.ComponentProps<typeof Button> {
  isHovered: boolean;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  children: React.ReactNode;
}

function HoverButton({
  isHovered,
  onMouseEnter,
  onMouseLeave,
  children,
  ...buttonProps
}: HoverButtonProps) {
  return (
    <div onMouseEnter={onMouseEnter} onMouseLeave={onMouseLeave}>
      <Button {...buttonProps} rightIcon={isHovered ? SvgX : SvgCheckSquare}>
        {children}
      </Button>
    </div>
  );
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
  const [isButtonHovered, setIsButtonHovered] = useState(false);

  const isSelected = status === "selected";
  const isConnected = status === "connected";
  const isDisconnected = status === "disconnected";

  const showEditButton = (isConnected || isSelected) && onEdit;
  const isCardClickable = isDisconnected && onConnect && !disabled;

  const handleCardClick = () => {
    if (isCardClickable) {
      onConnect?.();
    }
  };

  const getButtonConfig = () => {
    if (isDisconnected) {
      return {
        label: connectLabel,
        icon: SvgArrowExchange,
        onClick: onConnect,
        isHoverButton: false,
      };
    }

    if (isConnected) {
      return {
        label: selectLabel,
        icon: SvgArrowRightCircle,
        onClick: onSelect,
        isHoverButton: false,
      };
    }

    // Selected state
    return {
      label: selectedLabel,
      icon: SvgCheckSquare,
      onClick: onDeselect,
      isHoverButton: true,
    };
  };

  const buttonConfig = getButtonConfig();

  return (
    <div
      onClick={isCardClickable ? handleCardClick : undefined}
      className={cn(
        "flex items-start justify-between gap-3 rounded-16 border p-2",
        "bg-background-neutral-01",
        isSelected
          ? "border-action-link-05 bg-action-link-01"
          : "border-border-01",
        isCardClickable &&
          "cursor-pointer hover:bg-background-tint-01 transition-colors",
        disabled && "opacity-50 cursor-not-allowed",
        className
      )}
    >
      {/* Left section - Icon, Title, Description */}
      <div className="flex flex-1 items-start gap-1 px-2 py-1">
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
      <div className="flex items-center justify-end gap-2">
        {showEditButton && (
          <IconButton
            icon={SvgEdit}
            tooltip="Edit"
            internal
            tertiary
            onClick={noProp(onEdit)}
            className="h-6 w-6 opacity-70 hover:opacity-100"
            aria-label={`Edit ${title}`}
          />
        )}

        {buttonConfig.isHoverButton ? (
          <HoverButton
            isHovered={isButtonHovered}
            onMouseEnter={() => setIsButtonHovered(true)}
            onMouseLeave={() => setIsButtonHovered(false)}
            action
            tertiary
            disabled={disabled}
            onClick={noProp(buttonConfig.onClick)}
          >
            {buttonConfig.label}
          </HoverButton>
        ) : (
          <Button
            action={false}
            tertiary
            disabled={disabled || !buttonConfig.onClick}
            onClick={noProp(buttonConfig.onClick)}
            rightIcon={buttonConfig.icon}
          >
            {buttonConfig.label}
          </Button>
        )}
      </div>
    </div>
  );
}
