"use client";

import "@opal/components/end-of-list/styles.css";
import { Divider, Text } from "@opal/components";
import type { DividerSpacing } from "@opal/components/divider/components";
import type { RichStr } from "@opal/types";
import { spacingToRem } from "@opal/shared";

interface EndOfListProps {
  title: string | RichStr;
  /** Inset along the lines, as a spacing step (`N / 4` rem). Default: 0. */
  paddingParallel?: DividerSpacing;
  /** Inset across the lines, as a spacing step (`N / 4` rem). Default: 0. */
  paddingPerpendicular?: DividerSpacing;
}

function EndOfList({
  title,
  paddingParallel = 0,
  paddingPerpendicular = 0,
}: EndOfListProps) {
  return (
    <div
      className="opal-end-of-list"
      style={{
        paddingInline: spacingToRem(paddingParallel),
        paddingBlock: spacingToRem(paddingPerpendicular),
      }}
    >
      <Divider paddingParallel={0} paddingPerpendicular={0} />
      <Text font="secondary-body" color="text-03" wordWrap="whitespace-nowrap">
        {title}
      </Text>
      <Divider paddingParallel={0} paddingPerpendicular={0} />
    </div>
  );
}

export { EndOfList, type EndOfListProps };
