"use client";

import type { ReactNode } from "react";
import { useFormatter } from "next-intl";
import { Section } from "@opal/layouts";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { Text } from "@opal/components";
import { cn } from "@opal/utils";
import StatusTagPill from "@/views/admin/connectors/ConnectorDetailPage/StatusTagPill";
import type { StatusTag } from "@/views/admin/connectors/ConnectorDetailPage/statusTag";

/** Hides content once the line wraps. The query root sits 18 px inside a 640 px column when a run line's list is padded 4 px, so 620 px of line is a column under 640. More list padding wraps a 640 px column. */
export const LINE_NARROW_HIDDEN = "@max-[38.75rem]:hidden";

/** A connector row and a run line differ only in their narrow-card minimums and action spacing. A stat line holds figures over labels, its D sized to its control. */
export type LineVariant = "row" | "run" | "stat";

interface VariantClasses {
  a: string;
  b: string;
  c: string;
  d: string;
  third: string;
  /** Margin on A, B and C, for an inline inset larger than the block padding. */
  part: string;
  padding: 1 | 2;
  cAlign: "start" | "end";
  dGap: 1 | 2;
}

// Row and run lines wrap to A + D over B + C: below 640 px A's basis leaves room only for D. The parts' own 8 px padding is the line gap, which the design widens by 4 px on a run line and narrows by 4 px on a row.
const VARIANT_CLASSES = {
  row: {
    a: "@max-[38.75rem]:order-1 @max-[38.75rem]:min-w-[17.5rem] @max-[38.75rem]:basis-[calc(100%-4rem)]",
    b: "@max-[38.75rem]:order-3 @max-[38.75rem]:min-w-[11.75rem] @max-[38.75rem]:-mt-1",
    c: "@max-[38.75rem]:order-4 @max-[38.75rem]:min-w-[11.75rem] @max-[38.75rem]:max-w-[17.5rem] @max-[38.75rem]:-mt-1",
    d: "w-16 pe-1 @max-[38.75rem]:order-2",
    third: "",
    part: "",
    padding: 2,
    cAlign: "end",
    dGap: 1,
  },
  run: {
    // A run line's A splits into time and type, so it has no 280 px floor.
    a: "@max-[38.75rem]:order-1 @max-[38.75rem]:basis-[calc(100%-5.625rem)]",
    b: "@max-[38.75rem]:order-3 @max-[38.75rem]:min-w-[11.75rem] @max-[38.75rem]:mt-1",
    c: "@max-[38.75rem]:order-4 @max-[38.75rem]:min-w-[11.75rem] @max-[38.75rem]:max-w-[17.5rem] @max-[38.75rem]:mt-1",
    // Run-line actions fill the design's padded 64 px cell, 8 px apart.
    d: "w-16 ps-0.5 pe-1.5 py-1.5 @max-[38.75rem]:order-2 @max-[38.75rem]:min-w-[5.625rem]",
    third: "",
    part: "",
    padding: 2,
    cAlign: "end",
    dGap: 2,
  },
  // A stat card keeps C and its control on line 1 below 640 px and gives B line 2, so its button or picker stays top right. Parts pad 8 across and 4 down, the 188 and 280 px minimums include the margin.
  stat: {
    a: "@max-[38.75rem]:order-1 @max-[38.75rem]:min-w-[11.25rem]",
    b: "@max-[38.75rem]:order-4 @max-[38.75rem]:basis-full @max-[38.75rem]:min-w-[17rem] @max-[38.75rem]:mt-1",
    c: "@max-[38.75rem]:order-2 @max-[38.75rem]:min-w-[11.25rem]",
    // Sized to its control, which ends 4 px inside the card.
    d: "w-fit pe-1 @max-[38.75rem]:order-3",
    // A brushed span's picker label can outgrow 208 px, so the third grows instead of overlapping B.
    third: "min-w-fit",
    part: "mx-1",
    padding: 1,
    cAlign: "start",
    dGap: 1,
  },
} satisfies Record<LineVariant, VariantClasses>;

interface LineParts {
  a: ReactNode;
  b: ReactNode;
  /** A stat line leaves C out when it is null, so D takes the whole third. */
  c: ReactNode;
  d: ReactNode;
}

// A stat line sizes its third to C's picker, so only row and run lines can hand C's width to B.
export type LineLayoutProps = LineParts &
  (
    | { variant: "stat"; bSpansC?: never }
    | {
        variant: Exclude<LineVariant, "stat">;
        /** B's content runs on through C's slot, for a bar or table on one ruler across both; C is not drawn and the columns do not move. */
        bSpansC?: boolean;
      }
  );

// The columns stay put and only B's content runs on over C's empty slot: C is the third (a third of the line, at most 208 px) less D's 64 px, and the container is the line.
const B_SPANS_C_CONTENT =
  "w-[calc(100%_+_min(33.333cqw,13rem)_-_4rem)] @max-[38.75rem]:w-full";

/**
 * The three-column line shared by connector rows, run lines and stat cards: A and B split the width, C and D share a third capped at 208 px.
 * Below 640 px of card it wraps by variant, keeping the actions top right.
 */
export default function LineLayout({
  a,
  b,
  c,
  d,
  variant,
  bSpansC = false,
}: LineLayoutProps) {
  const variantClasses: VariantClasses = VARIANT_CLASSES[variant];
  const showsC = variant !== "stat" || c !== null;
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
          padding={variantClasses.padding}
          height="fit"
          className={cn(
            "min-w-0 flex-1",
            variantClasses.part,
            variantClasses.a
          )}
        >
          {a}
        </Section>
        <Section
          alignItems="start"
          gap={1}
          padding={variantClasses.padding}
          height="fit"
          className={cn(
            "min-w-0 flex-1",
            bSpansC && "@max-[38.75rem]:basis-full",
            variantClasses.part,
            variantClasses.b
          )}
        >
          {bSpansC ? (
            <Section
              alignItems="start"
              gap={1}
              height="fit"
              className={B_SPANS_C_CONTENT}
            >
              {b}
            </Section>
          ) : (
            b
          )}
        </Section>
        {/* A fixed third (flex-none would reset the basis) at the design's 208 px; below 640 px it dissolves so C and D wrap as the line's own parts. */}
        <Section
          flexDirection="row"
          justifyContent="end"
          alignItems="start"
          gap={0}
          height="fit"
          className={cn(
            "shrink-0 @max-[38.75rem]:contents max-w-[13rem] basis-1/3",
            variantClasses.third
          )}
        >
          {showsC && (
            <Section
              alignItems={variantClasses.cAlign}
              gap={1}
              padding={variantClasses.padding}
              height="fit"
              className={cn(
                "min-w-0 flex-1",
                variantClasses.part,
                variantClasses.c,
                bSpansC && "@max-[38.75rem]:hidden"
              )}
            >
              {!bSpansC && c}
            </Section>
          )}
          {/* 64 px holds two 24 px actions with a run line's gap and padding. */}
          <div className={cn("shrink-0", variantClasses.d)}>
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

// A figure that failed to load, so the line keeps its height and does not read as empty.
export const NO_FIGURE = "—";

export interface LineFigureProps {
  /** Null shows a dash. */
  value: number | null;
  label: string | RichStr;
}

/** A count over its label, for a part that stacks them. */
export function LineFigure({ value, label }: LineFigureProps) {
  const format = useFormatter();
  return (
    <>
      <Text font="main-content-emphasis" color="text-04">
        {value === null ? NO_FIGURE : format.number(value)}
      </Text>
      <Text font="secondary-body" color="text-03">
        {label}
      </Text>
    </>
  );
}

export interface LineTagsProps {
  tag: StatusTag;
  children?: ReactNode;
}

/** B's first line: the 20 px status tag, then the line's hints and counts, 8 apart. */
export function LineTags({ tag, children }: LineTagsProps) {
  return (
    <Section
      flexDirection="row"
      justifyContent="start"
      gap={2}
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
      <Text maxLines={1} overflowTooltip font="secondary-body" color="text-03">
        {label}
      </Text>
    </Section>
  );
}
