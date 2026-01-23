import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import { WithoutStyles } from "@/types";
import { IconProps } from "@opal/types";
import React from "react";

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
  auto: "w-auto flex-shrink-0",
  fit: "w-fit flex-shrink-0",
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
 * @param flexDirection - Flex direction. Default: "column".
 * @param justifyContent - Justify content along the main axis. Default: "center".
 * @param alignItems - Align items along the cross axis. Default: "center".
 * @param width - Width of the container: "auto", "fit", or "full". Default: "full".
 * @param height - Height of the container: "auto", "fit", or "full". Default: "full".
 * @param gap - Gap in REM units between children. Default: 1 (translates to gap-4 in Tailwind)
 * @param padding - Padding in REM units. Default: 0
 * @param wrap - If true, enables flex-wrap. Default: false
 * @param dbg - If true, adds a debug red border for visual debugging. Default: false
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
 *
 * // Section with fit width
 * <GeneralLayouts.Section width="fit">
 *   <Button>Fit to content</Button>
 * </GeneralLayouts.Section>
 * ```
 *
 * @remarks
 * - The component defaults to column layout when no direction is specified
 * - Full width and height by default
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

  ref?: React.Ref<HTMLDivElement>;
}
function Section({
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
 *
 * Variants:
 * - `primary`: Standard size (20px icon) with emphasized text. The default for prominent list items.
 * - `secondary`: Compact size (16px icon) with standard text. Use for denser lists or nested items.
 * - `tertiary`: Compact size (16px icon) with standard text. Use for less prominent items in tight layouts.
 * - `tertiary-muted`: Compact size (16px icon) with muted text styling. Use for de-emphasized or secondary information.
 *
 * @param icon - Optional icon component to display on the left
 * @param title - The main title text (required)
 * @param description - Optional description content below the title (string or ReactNode)
 * @param rightChildren - Optional content to render on the right side
 * @param variant - Visual variant. Default: "primary"
 * @param strikethrough - If true, applies line-through style to title. Default: false
 * @param loading - If true, renders skeleton placeholders instead of content. Default: false
 * @param center - If true, vertically centers items; otherwise aligns to start. Default: false
 */
type LineItemLayoutVariant =
  | "primary"
  | "secondary"
  | "tertiary"
  | "tertiary-muted";
export interface LineItemLayoutProps {
  icon?: React.FunctionComponent<IconProps>;
  title: string;
  description?: React.ReactNode;
  middleText?: string;
  rightChildren?: React.ReactNode;

  variant?: LineItemLayoutVariant;
  strikethrough?: boolean;
  loading?: boolean;
  center?: boolean;
  reducedPadding?: boolean;
}
function LineItemLayout({
  icon: Icon,
  title,
  description,
  middleText,
  rightChildren,

  variant = "primary",
  strikethrough,
  loading,
  center,
  reducedPadding,
}: LineItemLayoutProps) {
  // Derive styling from variant
  const isCompact =
    variant === "secondary" ||
    variant === "tertiary" ||
    variant === "tertiary-muted";
  const isMuted = variant === "tertiary-muted";

  return (
    <Section
      flexDirection="row"
      justifyContent="between"
      alignItems={center ? "center" : "start"}
      gap={1.5}
    >
      <div
        className="line-item-layout"
        data-variant={variant}
        data-has-icon={Icon ? "true" : undefined}
        data-loading={loading ? "true" : undefined}
        data-strikethrough={strikethrough ? "true" : undefined}
        data-reduced-padding={reducedPadding ? "true" : undefined}
      >
        {/* Row 1: Icon, Title */}
        {Icon && (
          <Icon size={isCompact ? 16 : 20} className="line-item-layout-icon" />
        )}
        {loading ? (
          <div className="line-item-layout-skeleton-title" />
        ) : (
          <Text
            mainContentEmphasis={!isCompact}
            text03={isMuted}
            className="line-item-layout-title"
          >
            {title}
          </Text>
        )}

        {/* Row 2: Description (column 2, or column 1 if no icon) */}
        {loading && description ? (
          <div className="line-item-layout-skeleton-description" />
        ) : description ? (
          <div className="line-item-layout-description">
            {typeof description === "string" ? (
              <Text secondaryBody text03>
                {description}
              </Text>
            ) : (
              description
            )}
          </div>
        ) : undefined}
      </div>

      {!loading && middleText && (
        <div className="flex-1">
          <Truncated text03 secondaryBody>
            {middleText}
          </Truncated>
        </div>
      )}

      {loading && rightChildren ? (
        <div className="line-item-layout-skeleton-right" />
      ) : rightChildren ? (
        <div className="flex-shrink-0">{rightChildren}</div>
      ) : undefined}
    </Section>
  );
}

export interface AttachmentItemLayoutProps
  // Omitted because this interface mandates them to be defined.
  extends Omit<LineItemLayoutProps, "description" | "icon"> {
  description: string;
  icon: React.FunctionComponent<IconProps>;
  variant?: "primary" | "secondary";
}
function AttachmentItemLayout({
  title,
  description,
  icon: Icon,
  middleText,
  rightChildren,
  variant = "primary",
}: AttachmentItemLayoutProps) {
  const content = (
    <Section flexDirection="row" gap={0.25} padding={0.25}>
      <div
        className={cn(
          "h-[2.25rem] aspect-square",
          variant === "primary" && "bg-background-tint-02 rounded-08"
        )}
      >
        <Section>
          <Icon className="attachment-button__icon" />
        </Section>
      </div>
      <LineItemLayout
        title={title}
        description={description}
        middleText={middleText}
        rightChildren={
          rightChildren ? (
            <div className="px-1">{rightChildren}</div>
          ) : undefined
        }
        center
        variant="secondary"
      />
    </Section>
  );

  if (variant === "primary") return content;

  return (
    <div className="w-full bg-background-tint-01 rounded-12">{content}</div>
  );
}

export { Section, LineItemLayout, AttachmentItemLayout };
