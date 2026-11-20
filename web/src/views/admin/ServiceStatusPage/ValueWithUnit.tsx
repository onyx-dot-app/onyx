"use client";

import { Text } from "@opal/components";
import type { RichStr } from "@opal/types";
import { richNodes } from "@opal/utils";

const SIZES = {
  // A summary or graph headline: "212 GB", "0.2 calls/s".
  headline: { value: "main-content-emphasis", unit: "main-ui-muted" },
  // A value in a list row: "24.1 M", "9 × 2 Copies".
  row: { value: "main-ui-body", unit: "secondary-body" },
} as const;

interface ValueWithUnitProps {
  value: string;
  unit?: string | RichStr;
  // A status after the unit, in the error color, e.g. "· 5 failed".
  note?: string | RichStr;
  size: keyof typeof SIZES;
}

/** A value and its unit on one line, so both share a text baseline. */
export default function ValueWithUnit({
  value,
  unit,
  note,
  size,
}: ValueWithUnitProps) {
  const fonts = SIZES[size];
  return (
    <Text font={fonts.value} color="text-04" as="p">
      {richNodes(
        <>
          {value}
          {unit && (
            <>
              {" "}
              <Text font={fonts.unit} color="text-03">
                {unit}
              </Text>
            </>
          )}
          {note && (
            <>
              {" "}
              <Text font="secondary-body" color="status-error-05">
                {note}
              </Text>
            </>
          )}
        </>
      )}
    </Text>
  );
}
