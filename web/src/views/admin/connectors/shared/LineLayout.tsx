"use client";

import type { ReactNode } from "react";
import { Section } from "@opal/layouts";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { OverflowText } from "@opal/components";
import { cn } from "@opal/utils";
import StatusTagPill from "@/views/admin/connectors/ConnectorDetailPage/StatusTagPill";
import type { StatusTag } from "@/views/admin/connectors/ConnectorDetailPage/statusTag";

/** Hides content once the line wraps. The query root sits 18 px inside a 640 px column when a run line's list is padded 4 px, so 620 px of line is a column under 640. More list padding wraps a 640 px column. */
export const LINE_NARROW_HIDDEN = "@max-[38.75rem]:hidden";

/** A connector row and a run line differ only in their narrow-card minimums and action spacing. */
export type LineVariant = "row" | "run";

// Below 640 px A's basis leaves room only for D, so B and C wrap under them. On a card the parts' own 8 px padding is the line gap, a run line adds 4 px.
const VARIANT_CLASSES = {
  row: {
    a: "@max-[38.75rem]:min-w-[17.5rem] @max-[38.75rem]:basis-[calc(100%-4rem)]",
    bc: "",
    d: "pe-1",
    dGap: 1,
  },
  run: {
    // A run line's A splits into time and type, so it has no 280 px floor.
    a: "@max-[38.75rem]:basis-[calc(100%-5.625rem)]",
    bc: "@max-[38.75rem]:mt-1",
    // Run-line actions fill the design's padded 64 px cell, 8 px apart.
    d: "ps-0.5 pe-1.5 py-1.5 @max-[38.75rem]:min-w-[5.625rem]",
    dGap: 2,
  },
} satisfies Record<
  LineVariant,
  { a: string; bc: string; d: string; dGap: 1 | 2 }
>;

export interface LineLayoutProps {
  a: ReactNode;
  b: ReactNode;
  c: ReactNode;
  d: ReactNode;
  variant: LineVariant;
}

/**
 * The three-column line shared by connector rows and run lines: A and B split the width, C and a 64 px D share a third capped at 208 px.
 * Below 640 px of card it wraps to A + D over B + C, keeping the actions top right.
 */
export default function LineLayout({ a, b, c, d, variant }: LineLayoutProps) {
  const variantClasses = VARIANT_CLASSES[variant];
  // A container query cannot measure its own element, so the parts query this wrapper.
  return (
    <div className="@container w-full">
      <Section
        flexDirection="row"
        justifyContent="start"
        alignItems="start"
        gap={0}
        height="fit"
        className="@max-[38.75rem]:flex-wrap"
      >
        <Section
          alignItems="start"
          gap={1}
          padding={2}
          height="fit"
          className={cn(
            "min-w-0 flex-1 @max-[38.75rem]:order-1",
            variantClasses.a
          )}
        >
          {a}
        </Section>
        <Section
          alignItems="start"
          gap={1}
          padding={2}
          height="fit"
          className={cn(
            "min-w-0 flex-1 @max-[38.75rem]:order-3 @max-[38.75rem]:min-w-[11.75rem]",
            variantClasses.bc
          )}
        >
          {b}
        </Section>
        {/* A fixed third (flex-none would reset the basis) at the design's 208 px; below 640 px it dissolves so D and C take separate lines. */}
        <Section
          flexDirection="row"
          alignItems="start"
          gap={0}
          height="fit"
          className="max-w-[13rem] shrink-0 basis-1/3 @max-[38.75rem]:contents"
        >
          <Section
            alignItems="end"
            gap={1}
            padding={2}
            height="fit"
            className={cn(
              "min-w-0 flex-1 @max-[38.75rem]:order-4 @max-[38.75rem]:min-w-[11.75rem] @max-[38.75rem]:max-w-[17.5rem]",
              variantClasses.bc
            )}
          >
            {c}
          </Section>
          {/* 64 px holds two 24 px actions with a run line's gap and padding. */}
          <div
            className={cn(
              "w-16 shrink-0 @max-[38.75rem]:order-2",
              variantClasses.d
            )}
          >
            <Section
              flexDirection="row"
              justifyContent="end"
              gap={variantClasses.dGap}
              height="fit"
            >
              {d}
            </Section>
          </div>
        </Section>
      </Section>
    </div>
  );
}

export interface LineTagsProps {
  tag: StatusTag;
  children?: ReactNode;
}

/** B's first line: the 20 px status tag, then the line's hints and counts. */
export function LineTags({ tag, children }: LineTagsProps) {
  return (
    <Section
      flexDirection="row"
      justifyContent="start"
      gap={1}
      width="fit"
      height="fit"
    >
      <StatusTagPill tag={tag} size={5} />
      {children}
    </Section>
  );
}

export interface LineIconLabelProps {
  icon: IconFunctionComponent;
  label: string | RichStr;
}

/** A 12 px glyph in a 16 px box before a muted one-line label; a clipped label shows in full on hover. */
export function LineIconLabel({ icon: Icon, label }: LineIconLabelProps) {
  return (
    <Section
      flexDirection="row"
      justifyContent="start"
      gap={0.25}
      width="fit"
      height="fit"
      className="min-w-0 max-w-full"
    >
      <Section width={1} height={1} className="shrink-0">
        <Icon size={12} className="stroke-text-02" />
      </Section>
      <OverflowText font="secondary-body" color="text-03">
        {label}
      </OverflowText>
    </Section>
  );
}
