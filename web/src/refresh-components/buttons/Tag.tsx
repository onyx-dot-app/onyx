"use client";

import React from "react";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { SvgX } from "@opal/icons";
import type { IconProps } from "@opal/types";

const variantStyles = {
  display: {
    container: "flex items-center p-1",
    icon: "size-4 stroke-text-03",
    text: { secondaryBody: true, text03: true },
  },
  editable: {
    container: "flex items-center gap-1 px-2 py-1",
    icon: "size-3 stroke-text-03",
    text: { mainUiBody: true, text04: true },
  },
} as const;

export interface TagProps {
  label: string;
  variant?: "display" | "editable";
  icon?: React.FunctionComponent<IconProps>;
  onRemove?: () => void;
  onClick?: () => void;
  className?: string;
  ref?: React.Ref<HTMLDivElement>;
}

export default function Tag({
  label,
  variant = "display",
  icon: Icon,
  onRemove,
  onClick,
  className,
  ref,
}: TagProps) {
  const styles = variantStyles[variant];

  return (
    <div
      ref={ref}
      className={cn(
        styles.container,
        "rounded-08",
        "bg-background-tint-02 hover:bg-background-tint-03",
        "focus-visible:shadow-[0_0_0_2px_var(--background-tint-04)]",
        "outline-none transition-colors",
        onClick || variant === "display" ? "cursor-pointer" : undefined,
        className
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
      {Icon && <Icon className={styles.icon} />}
      <Text {...styles.text}>{label}</Text>
      {onRemove && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="p-0.5 stroke-text-02 hover:stroke-text-03"
          aria-label={`Remove ${label} filter`}
        >
          <SvgX className="size-3" />
        </button>
      )}
    </div>
  );
}
