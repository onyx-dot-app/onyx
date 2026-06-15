"use client";

import Image from "next/image";

import { glomiLogoMark, glomiWordmark } from "@/assets/brand";
import { APP_NAME } from "@/lib/brand";
import { cn } from "@opal/utils";
import type { IconProps } from "@opal/types";

export function GlomiLogoMark({
  size = 24,
  width,
  height,
  className,
  title,
}: IconProps) {
  const resolvedSize = size ?? width ?? height ?? 24;
  const resolvedWidth = width ?? resolvedSize;
  const resolvedHeight = height ?? resolvedSize;
  const sizeHint =
    typeof resolvedSize === "number" ? `${resolvedSize}px` : undefined;

  return (
    <span
      className={cn(
        "relative flex shrink-0 overflow-hidden rounded-08",
        className
      )}
      style={{
        width: resolvedWidth,
        height: resolvedHeight,
      }}
      role="img"
      aria-label={title ?? APP_NAME}
    >
      <Image
        src={glomiLogoMark}
        alt=""
        aria-hidden
        fill
        sizes={sizeHint}
        className="object-contain"
      />
    </span>
  );
}

export function GlomiLogotype({
  size = 24,
  className,
}: {
  size?: number;
  className?: string;
}) {
  const width = Math.round(size * (glomiWordmark.width / glomiWordmark.height));

  return (
    <span
      className={cn("relative flex shrink-0", className)}
      style={{ width, height: size }}
      role="img"
      aria-label={APP_NAME}
    >
      <Image
        src={glomiWordmark}
        alt=""
        aria-hidden
        fill
        sizes={`${width}px`}
        className="object-contain"
        priority
      />
    </span>
  );
}
