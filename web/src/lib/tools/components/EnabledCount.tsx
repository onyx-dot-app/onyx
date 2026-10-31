"use client";

import { type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { richNodes } from "@opal/utils";

interface EnabledCountProps {
  enabledCount: number;
  totalCount: number;
}

/**
 * How many of a set of tools are switched on, e.g. "3 of 12".
 *
 * The noun is left to the surrounding row, which already names what is being
 * counted — every call site is a tool context.
 */
export default function EnabledCount({
  enabledCount,
  totalCount,
}: EnabledCountProps) {
  const t = useTranslations("common");

  // The enabled figure is picked out from the rest of the phrase. It has to
  // be a tag rather than a separate element, because where the number falls
  // in the sentence is the translation's business, not this component's.
  function value(chunks: ReactNode) {
    return <Text color="action-selection-05">{richNodes(chunks)}</Text>;
  }

  return (
    <Text color="text-03">
      {richNodes(
        t.rich("enabledCount.label", {
          enabled: enabledCount,
          total: totalCount,
          value,
        })
      )}
    </Text>
  );
}
