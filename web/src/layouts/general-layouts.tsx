import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { WithoutStyles } from "@/types";
import { IconProps } from "@opal/types";
import React, { forwardRef } from "react";

export type FlexDirection = "row" | "column";
export type JustifyContent = "start" | "center" | "end" | "between";
export type AlignItems = "start" | "center" | "end" | "stretch";
export type Length = "auto" | "fit" | "full";

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
const widthClassmap: Record<Length, string> = {
  auto: "w-auto",
  fit: "w-fit",
  full: "w-full",
};
const heightClassmap: Record<Length, string> = {
  auto: "h-auto",
  fit: "h-fit",
  full: "h-full",
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
  width?: Length;
  height?: Length;

  gap?: number;
  padding?: number;
  wrap?: boolean;

  // Debugging utilities
  dbg?: boolean;
}
const Section = forwardRef<HTMLDivElement, SectionProps>(
  (
    {
      flexDirection = "column",
      justifyContent = "center",
      alignItems = "center",
      width = "full",
      height = "full",
      gap = 1,
      padding = 0,
      wrap,
      dbg,
      ...rest
    },
    ref
  ) => {
    return (
      <div
        ref={ref}
        className={cn(
          "flex",

          flexDirectionClassMap[flexDirection],
          justifyClassMap[justifyContent],
          alignClassMap[alignItems],
          widthClassmap[width],
          heightClassmap[height],

          wrap && "flex-wrap",
          dbg && "dbg-red"
        )}
        style={{ gap: `${gap}rem`, padding: `${padding}rem` }}
        {...rest}
      />
    );
  }
);
Section.displayName = "Section";

export interface LineItemLayoutProps {
  icon?: React.FunctionComponent<IconProps>;
  title: React.ReactNode;
  description?: React.ReactNode;
  rightChildren?: React.ReactNode;

  compact?: boolean;
  strikethrough?: boolean;
  secondary?: boolean;
}
/**
 * LineItemLayout - A layout for icon + title + description rows
 *
 * Structure:
 *   Flexbox Row [
 *     Grid [
 *       [Icon] [Title      ]
 *       [    ] [Description]
 *     ],
 *     rightChildren
 *   ]
 *
 * - Icon column auto-sizes to icon width
 * - Icon vertically centers with title
 * - Description aligns with title's left edge (both in grid column 2)
 * - rightChildren is outside the grid, in the outer flexbox
 */
function LineItemLayout({
  icon: Icon,
  title,
  description,
  rightChildren,

  compact,
  strikethrough,
  secondary,
}: LineItemLayoutProps) {
  return (
    <Section flexDirection="row" justifyContent="between" alignItems="start">
      <div
        className="grid flex-1"
        style={{
          gridTemplateColumns: Icon ? "auto 1fr" : "1fr",
          columnGap: "0.5rem",
        }}
      >
        {/* Row 1: Icon, Title */}
        {Icon && (
          <Icon
            size={compact ? 16 : 20}
            className={cn(
              "self-center",
              secondary ? "stroke-text-03" : "stroke-text-04"
            )}
          />
        )}
        {typeof title === "string" ? (
          <Text
            mainContentEmphasis={!secondary}
            text03={secondary}
            className={cn(strikethrough && "line-through")}
          >
            {title}
          </Text>
        ) : (
          title
        )}

        {/* Row 2: Description (column 2, or column 1 if no icon) */}
        {description && (
          <div className={cn("leading-none", Icon && "col-start-2")}>
            {typeof description === "string" ? (
              <Text secondaryBody text03>
                {description}
              </Text>
            ) : (
              description
            )}
          </div>
        )}
      </div>

      {rightChildren && <div className="flex-shrink-0">{rightChildren}</div>}
    </Section>
  );
}

export { Section, LineItemLayout };
