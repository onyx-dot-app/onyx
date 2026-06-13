"use client";

import { APP_NAME } from "@/lib/brand";
import { cn } from "@opal/utils";
import type { IconProps } from "@opal/types";

export function GlomiLogoMark({
  size = 24,
  width,
  height,
  className,
}: IconProps) {
  const resolvedSize = size ?? width ?? height ?? 24;

  return (
    <div
      className={cn(
        "shrink-0 rounded-08 bg-theme-primary-05 text-text-inverted-05 flex items-center justify-center font-bold",
        className
      )}
      style={{
        width: width ?? resolvedSize,
        height: height ?? resolvedSize,
        fontSize: Math.max(12, resolvedSize * 0.5),
      }}
      aria-label={APP_NAME}
    >
      G
    </div>
  );
}

export function GlomiLogotype({
  size = 24,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <div
      className={cn("flex items-center gap-2 min-w-0", className)}
      aria-label={APP_NAME}
    >
      <GlomiLogoMark size={size} />
      <span
        className="font-semibold text-text-05 whitespace-nowrap"
        style={{ fontSize: Math.max(16, size * 0.72), lineHeight: 1 }}
      >
        {APP_NAME}
      </span>
    </div>
  );
}
