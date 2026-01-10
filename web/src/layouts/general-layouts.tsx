import { cn } from "@/lib/utils";
import { WithoutStyles } from "@/types";
import React, { forwardRef } from "react";

export type FlexDirection = "row" | "column";
export type JustifyContent = "start" | "center" | "end" | "between";
export type AlignItems = "start" | "center" | "end";

const directionClassMap: Record<FlexDirection, string> = {
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
};

/**
 * Section - A flexible container component for grouping related content
 *
 * Provides a standardized layout container with configurable direction and spacing.
 * Uses flexbox layout with customizable gap between children. Defaults to column layout.
 *
 * @param flexDirection - Flex direction. Default: column.
 * @param justifyContent - Justify content along the main axis. Default: center.
 * @param alignItems - Align items along the cross axis. Default: center.
 * @param gap - Gap in REM units between children. Default: 1 (translates to gap-4 in Tailwind)
 * @param padding - Padding in REM units. Default: 0
 * @param fit - If true, uses w-fit instead of w-full. Default: false
 * @param wrap - If true, enables flex-wrap. Default: false
 * @param children - React children to render inside the section
 *
 * @example
 * ```tsx
 * import * as GeneralLayouts from "@/layouts/general-layouts";
 *
 * // Column section with default gap - centered
 * <GeneralLayouts.Section>
 *   <Card>First item</Card>
 *   <Card>Second item</Card>
 * </GeneralLayouts.Section>
 *
 * // Row section aligned to the left and vertically centered
 * <GeneralLayouts.Section flexDirection="row" justifyContent="start" alignItems="center">
 *   <Button>Cancel</Button>
 *   <Button>Save</Button>
 * </GeneralLayouts.Section>
 *
 * // Column section with items aligned to the right
 * <GeneralLayouts.Section alignItems="end" gap={2}>
 *   <InputTypeIn label="Name" />
 *   <InputTypeIn label="Email" />
 * </GeneralLayouts.Section>
 *
 * // Row section centered both ways
 * <GeneralLayouts.Section flexDirection="row" justifyContent="center" alignItems="center">
 *   <Text>Centered content</Text>
 * </GeneralLayouts.Section>
 * ```
 *
 * @remarks
 * - The component defaults to column layout when no direction is specified
 * - Full width by default (w-full) unless fit is true
 * - Prevents style overrides (className and style props are not available)
 * - Import using namespace import for consistent usage: `import * as GeneralLayouts from "@/layouts/general-layouts"`
 */
export interface SectionProps
  extends WithoutStyles<React.HtmlHTMLAttributes<HTMLDivElement>> {
  flexDirection?: FlexDirection;
  justifyContent?: JustifyContent;
  alignItems?: AlignItems;
  gap?: number;
  padding?: number;
  fit?: boolean;
  wrap?: boolean;
}

const Section = forwardRef<HTMLDivElement, SectionProps>(
  (
    {
      flexDirection = "column",
      justifyContent = "center",
      alignItems = "center",
      gap = 1,
      padding = 0,
      fit,
      wrap,
      ...rest
    },
    ref
  ) => {
    const width = fit ? "w-fit" : "w-full";

    return (
      <div
        ref={ref}
        className={cn(
          "flex",
          wrap && "flex-wrap",
          justifyClassMap[justifyContent],
          alignClassMap[alignItems],
          width,
          directionClassMap[flexDirection]
        )}
        style={{ gap: `${gap}rem`, padding: `${padding}rem` }}
        {...rest}
      />
    );
  }
);
Section.displayName = "Section";

export { Section };
