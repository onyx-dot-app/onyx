"use client";

import type { ReactNode } from "react";
import { SettingsLayouts, Section } from "@opal/layouts";
import { cn } from "@opal/utils";

/** The panel beside the column from 816 px of `page-body` content, the design's stack point, and under it below. Tailwind reads whole literals, so each class spells the width out. */
export const BESIDE = {
  row: "@max-[51rem]/page-body:flex-col @max-[51rem]/page-body:items-stretch",
  // 640 px is the design's column width beside the panel. Stacked, it takes the full width.
  column: "@min-[51rem]/page-body:max-w-[40rem]",
  // Nearest container is the body's, so no name. self-stretch fills the column's height and size containment keeps the list from growing the row, so it scrolls inside.
  panel:
    "@min-[51rem]:w-100 @min-[51rem]:shrink-0 @min-[51rem]:h-auto @min-[51rem]:self-stretch @min-[51rem]:contain-size",
  // Capped at the panel's height, so the list scrolls inside the card.
  panelBody: "@min-[51rem]:max-h-full",
  // Stacked, the panel can be a page's only error list, so it hides only beside the column.
  panelHidden: "@min-[51rem]:hidden",
  // 1.5rem and 6rem match SettingsLayouts.Body's pt-6 and pt-6 + pb-18, so the page's end never pushes the title out of view.
  panelSticky:
    "@min-[51rem]:sticky @min-[51rem]:top-[calc(var(--settings-header-height,0px)_+_1.5rem)] @min-[51rem]:max-h-[min(100%,calc(var(--settings-scroll-height)_-_var(--settings-header-height,0px)_-_6rem))]",
  // Named, so a control inside a LineLayout's own container still measures the body.
  hiddenStacked: "@max-[51rem]/page-body:hidden",
  hiddenBeside: "@min-[51rem]/page-body:hidden",
};

/** Whether the body row holding `panel` has stacked it under the column. The stack point is a container query, so only the row's computed direction knows it. */
export function isStacked(panel: HTMLElement): boolean {
  const row = panel.parentElement;
  return (
    row !== null && window.getComputedStyle(row).flexDirection === "column"
  );
}

export interface PanelPageBodyProps {
  children: ReactNode;
  panel?: ReactNode;
}

/** The column and the Activities panel beside it, the panel under the column below 816 px of content. */
export default function PanelPageBody({ children, panel }: PanelPageBodyProps) {
  return (
    <SettingsLayouts.Body>
      <Section height="fit" className="@container/page-body">
        {/* Centered, so the column keeps its place under the header while the panel is hidden. */}
        <Section
          flexDirection="row"
          alignItems="start"
          justifyContent="center"
          gap={4}
          height="fit"
          className={BESIDE.row}
        >
          {/* min-w-0 lets the column shrink under long content. */}
          <Section
            alignItems="stretch"
            gap={6}
            height="fit"
            className={cn("min-w-0 flex-1", BESIDE.column)}
          >
            {children}
          </Section>
          {panel}
        </Section>
      </Section>
    </SettingsLayouts.Body>
  );
}
