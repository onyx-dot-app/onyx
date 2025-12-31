"use client";

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
 * @param children - React children to render inside the section
 *
 * @example
 * ```tsx
 * import * as GeneralLayouts from "@/layouts/general-layouts";
 *
 * // Vertical section with default gap (1rem = gap-4) - default behavior
 * <GeneralLayouts.Section>
 *   <Card>First item</Card>
 *   <Card>Second item</Card>
 * </GeneralLayouts.Section>
 *
 * // Horizontal section with custom gap
 * <GeneralLayouts.Section horizontal gap={2}>
 *   <Button>Cancel</Button>
 *   <Button>Save</Button>
 * </GeneralLayouts.Section>
 *
 * // Explicitly vertical section with larger gap
 * <GeneralLayouts.Section vertical gap={3}>
 *   <InputTypeIn label="Name" />
 *   <InputTypeIn label="Email" />
 * </GeneralLayouts.Section>
 * ```
 *
 * @remarks
 * - The component defaults to vertical layout (flex-col) when no direction is specified
 * - The component uses Tailwind's gap utilities (gap-4, gap-8, gap-12, etc.)
 * - Gap values are multiplied by 4 for Tailwind classes (gap=1 -> gap-4, gap=2 -> gap-8)
 * - Full width by default (w-full)
 * - Prevents style overrides (className and style props are not available)
 * - Import using namespace import for consistent usage: `import * as GeneralLayouts from "@/layouts/general-layouts"`
 */
export interface SectionProps
  extends WithoutStyles<React.HtmlHTMLAttributes<HTMLDivElement>> {
  vertical?: boolean;
  horizontal?: boolean;
  gap?: number;
  fit?: boolean;
}

export function Section({
  vertical,
  horizontal,
  gap = 1,
  fit,
  ...rest
}: SectionProps) {
  // Determine direction: horizontal overrides vertical, default is vertical
  const direction = horizontal ? "flex-row" : "flex-col";
  const width = fit ? "w-fit" : "w-full";

  return (
    <div
      className={cn("flex", width, direction)}
      style={{ gap: `${gap}rem` }}
      {...rest}
    />
  );
}
