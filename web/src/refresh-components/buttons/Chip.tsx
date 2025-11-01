"use client";

import React from "react";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgX from "@/icons/x";

export interface ChipProps {
  // Chip states
  disabled?: boolean;

  // Content
  label: string;
  onRemove?: () => void;
  className?: string;
}

export default function Chip({
  disabled,
  label,
  onRemove,
  className,
}: ChipProps) {
  return (
    <div
      className={cn(
        "flex items-center gap-2 px-2 py-1 bg-background-tint-01 border border-border-01 rounded-08 w-fit",
        disabled && "opacity-50",
        className
      )}
    >
      <Text mainUiMuted>{label}</Text>
      {onRemove && !disabled && (
        <IconButton tertiary icon={SvgX} onClick={onRemove} tooltip="Remove" />
      )}
    </div>
  );
}
