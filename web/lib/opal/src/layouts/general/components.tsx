"use client";

import React from "react";
import { cn } from "@opal/utils";
import type { Spacing, WithoutStyles } from "@opal/types";
import { spacingToRem } from "@opal/shared";

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

interface SectionProps extends WithoutStyles<
  React.HtmlHTMLAttributes<HTMLDivElement>
> {
  className?: string;
  flexDirection?: FlexDirection;
  justifyContent?: JustifyContent;
  alignItems?: AlignItems;
  width?: Length;
  height?: Length;

  /** Spacing between children, as a {@link Spacing} step (`N / 4` rem). @default 4 */
  gap?: Spacing;
  /** Inner padding, as a {@link Spacing} step (`N / 4` rem). @default 0 */
  padding?: Spacing;
  wrap?: boolean;
  /** Spacing between wrapped lines, as a {@link Spacing} step. @default gap */
  wrapGap?: Spacing;

  /** As a flex child: the share of the free space it takes. Setting it, or
   * `basis`, lets the content shrink below its own width. */
  grow?: number;
  /** As a flex child: `false` keeps it from shrinking. @default true */
  shrink?: boolean;
  /** As a flex child: its starting size along the parent's row or column, in rem. */
  basis?: number;
  /** Minimum height, in rem. */
  minHeight?: number;

  ref?: React.Ref<HTMLDivElement>;
}

function Section({
  className,
  flexDirection = "column",
  justifyContent = "center",
  alignItems = "center",
  width = "full",
  height = "full",
  gap = 4,
  padding = 0,
  wrap,
  wrapGap,
  grow,
  shrink = true,
  basis,
  minHeight,
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
        (grow !== undefined || basis !== undefined) && "min-w-0",
        !shrink && "shrink-0",
        className
      )}
      style={{
        // Longhands only: React drops a removed longhand without re-applying
        // a `gap` shorthand beside it.
        rowGap: spacingToRem(flexDirection === "row" ? (wrapGap ?? gap) : gap),
        columnGap: spacingToRem(
          flexDirection === "row" ? gap : (wrapGap ?? gap)
        ),
        padding: spacingToRem(padding),
        ...(typeof width === "number" && { width: `${width}rem` }),
        ...(typeof height === "number" && { height: `${height}rem` }),
        ...(grow !== undefined && { flexGrow: grow }),
        ...(basis !== undefined && { flexBasis: `${basis}rem` }),
        ...(minHeight !== undefined && { minHeight: `${minHeight}rem` }),
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
