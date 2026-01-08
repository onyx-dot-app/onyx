import { cn } from "@/lib/utils";
import { WithoutStyles } from "@/types";
import React from "react";

/**
 * Section - A flexible container component for grouping related content
 *
 * Provides a standardized layout container with configurable direction and spacing.
 * Uses flexbox layout with customizable gap between children. Defaults to vertical layout.
 *
 * @param vertical - If true, arranges children vertically (flex-col). Default: true.
 * @param horizontal - If true, arranges children horizontally (flex-row). Overrides vertical.
 * @param gap - Gap in REM units between children. Default: 1 (translates to gap-4 in Tailwind)
 * @param padding - Padding in REM units. Default: 0
 * @param fit - If true, uses w-fit instead of w-full. Default: false
 * @param wrap - If true, enables flex-wrap. Default: false
 * @param left - Aligns content to the left (visually)
 * @param right - Aligns content to the right (visually)
 * @param top - Aligns content to the top (visually)
 * @param bottom - Aligns content to the bottom (visually)
 * @param hCenter - Centers content horizontally (visually)
 * @param vCenter - Centers content vertically (visually)
 * @param children - React children to render inside the section
 *
 * @example
 * ```tsx
 * import * as GeneralLayouts from "@/layouts/general-layouts";
 *
 * // Vertical section with default gap - centered
 * <GeneralLayouts.Section>
 *   <Card>First item</Card>
 *   <Card>Second item</Card>
 * </GeneralLayouts.Section>
 *
 * // Horizontal section aligned to the left and vertically centered
 * <GeneralLayouts.Section horizontal left vCenter>
 *   <Button>Cancel</Button>
 *   <Button>Save</Button>
 * </GeneralLayouts.Section>
 *
 * // Vertical section with items aligned to the right
 * <GeneralLayouts.Section vertical right gap={2}>
 *   <InputTypeIn label="Name" />
 *   <InputTypeIn label="Email" />
 * </GeneralLayouts.Section>
 *
 * // Horizontal section centered both ways
 * <GeneralLayouts.Section horizontal hCenter vCenter>
 *   <Text>Centered content</Text>
 * </GeneralLayouts.Section>
 * ```
 *
 * @remarks
 * - The component defaults to vertical layout (flex-col) when no direction is specified
 * - Alignment props (left, right, top, bottom, hCenter, vCenter) are orientation-agnostic
 * - Left/right always control horizontal alignment regardless of flex direction
 * - Top/bottom always control vertical alignment regardless of flex direction
 * - Do not specify conflicting props (e.g., both left and right) - first truthy value wins
 * - Full width by default (w-full) unless fit is true
 * - Prevents style overrides (className and style props are not available)
 * - Import using namespace import for consistent usage: `import * as GeneralLayouts from "@/layouts/general-layouts"`
 */
export interface SectionProps
  extends WithoutStyles<React.HtmlHTMLAttributes<HTMLDivElement>> {
  vertical?: boolean;
  horizontal?: boolean;
  gap?: number;
  padding?: number;
  fit?: boolean;
  wrap?: boolean;

  // Orientation-agnostic alignment props
  left?: boolean;
  right?: boolean;
  top?: boolean;
  bottom?: boolean;
  hCenter?: boolean;
  vCenter?: boolean;
}

export function Section({
  vertical,
  horizontal,
  gap = 1,
  padding = 0,
  fit,
  wrap,
  left,
  right,
  top,
  bottom,
  hCenter,
  vCenter,
  ...rest
}: SectionProps) {
  // Determine direction: horizontal overrides vertical, default is vertical
  const isHorizontal = horizontal && !vertical;
  const direction = isHorizontal ? "flex-row" : "flex-col";
  const width = fit ? "w-fit" : "w-full";

  // For horizontal layouts (flex-row):
  //   - left/right/hCenter control justify-content (main axis)
  //   - top/bottom/vCenter control align-items (cross axis)
  // For vertical layouts (flex-col):
  //   - top/bottom/vCenter control justify-content (main axis)
  //   - left/right/hCenter control align-items (cross axis)

  let justifyContent: string;
  let alignItems: string;

  if (isHorizontal) {
    // Horizontal layout: left/right/hCenter → justify-content
    justifyContent = left
      ? "justify-start"
      : right
        ? "justify-end"
        : hCenter
          ? "justify-center"
          : "justify-center";

    // Horizontal layout: top/bottom/vCenter → align-items
    alignItems = top
      ? "items-start"
      : bottom
        ? "items-end"
        : vCenter
          ? "items-center"
          : "items-center";
  } else {
    // Vertical layout: top/bottom/vCenter → justify-content
    justifyContent = top
      ? "justify-start"
      : bottom
        ? "justify-end"
        : vCenter
          ? "justify-center"
          : "justify-center";

    // Vertical layout: left/right/hCenter → align-items
    alignItems = left
      ? "items-start"
      : right
        ? "items-end"
        : hCenter
          ? "items-center"
          : "items-center";
  }

  return (
    <div
      className={cn(
        "flex w-full",
        wrap && "flex-wrap",
        justifyContent,
        alignItems,
        width,
        direction
      )}
      style={{ gap: `${gap}rem`, padding: `${padding}rem` }}
      {...rest}
    />
  );
}
