"use client";

import React from "react";
import { cn } from "@/lib/utils";

interface ToggleProps {
  isEnabled: boolean;
  onClick: () => void;
  ariaLabel: string;
  className?: string;
  enabledClassName: string;
  disabledClassName: string;
  thumbBaseClassName: string;
  enabledThumbClassName: string;
  disabledThumbClassName: string;
  style?: React.CSSProperties;
  thumbStyle?: React.CSSProperties;
}

export function Toggle({
  isEnabled,
  onClick,
  ariaLabel,
  className,
  enabledClassName,
  disabledClassName,
  thumbBaseClassName,
  enabledThumbClassName,
  disabledThumbClassName,
  style,
  thumbStyle,
}: ToggleProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "relative transition-colors",
        className,
        isEnabled ? enabledClassName : disabledClassName
      )}
      aria-pressed={isEnabled}
      aria-label={ariaLabel}
      style={style}
    >
      <div
        className={cn(
          "absolute transition-transform duration-200 ease-in-out",
          thumbBaseClassName,
          isEnabled ? enabledThumbClassName : disabledThumbClassName
        )}
        style={thumbStyle}
      />
    </button>
  );
}
