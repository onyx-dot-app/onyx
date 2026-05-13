"use client";

import React from "react";
import { cn } from "@opal/utils";
import type { WithoutStyles } from "@opal/types";

type FlexDirection = "row" | "column";
type JustifyContent = "start" | "center" | "end" | "between";
type AlignItems = "start" | "center" | "end" | "stretch";
type Length = "auto" | "fit" | "full" | number;

const flexDirectionClassMap: Record<FlexDirection, string> = {
  row: "flex-row",
  column: "flex-col",
};
const justifyClassMap: Record<JustifyContent, string> = {
  start: "justify-start",
  center: "justify-center",
  end: "justify-end",
  between: "justify-between",
};
const alignClassMap: Record<AlignItems, string> = {
  start: "items-start",
  center: "items-center",
  end: "items-end",
  stretch: "items-stretch",
};
const widthClassmap: Record<Exclude<Length, number>, string> = {
  auto: "w-auto shrink-0",
  fit: "w-fit shrink-0",
  full: "w-full",
};
const heightClassmap: Record<Exclude<Length, number>, string> = {
  auto: "h-auto",
  fit: "h-fit",
  full: "h-full min-h-0",
};

interface SectionProps
  extends WithoutStyles<React.HtmlHTMLAttributes<HTMLDivElement>> {
  className?: string;
  flexDirection?: FlexDirection;
  justifyContent?: JustifyContent;
  alignItems?: AlignItems;
  width?: Length;
  height?: Length;

  gap?: number;
  padding?: number;
  wrap?: boolean;

  dbg?: boolean;

  ref?: React.Ref<HTMLDivElement>;
}

function Section({
  className,
  flexDirection = "column",
  justifyContent = "center",
  alignItems = "center",
  width = "full",
  height = "full",
  gap = 1,
  padding = 0,
  wrap,
  dbg,
  ref,
  ...rest
}: SectionProps) {
  return (
    <div
      ref={ref}
      className={cn(
        "flex",

        flexDirectionClassMap[flexDirection],
        justifyClassMap[justifyContent],
        alignClassMap[alignItems],
        typeof width === "string" && widthClassmap[width],
        typeof height === "string" && heightClassmap[height],
        typeof height === "number" && "overflow-hidden",

        wrap && "flex-wrap",
        dbg && "dbg-red",
        className
      )}
      style={{
        gap: `${gap}rem`,
        padding: `${padding}rem`,
        ...(typeof width === "number" && { width: `${width}rem` }),
        ...(typeof height === "number" && { height: `${height}rem` }),
      }}
      {...rest}
    />
  );
}

export {
  Section,
  widthClassmap,
  heightClassmap,
  type SectionProps,
  type FlexDirection,
  type JustifyContent,
  type AlignItems,
  type Length,
};
