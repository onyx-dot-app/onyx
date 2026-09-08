"use client";

import { type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { richNodes } from "@opal/utils";

interface EnabledCountProps {
  enabledCount: number;
  totalCount: number;
  /**
   * What is being counted, when the count reads better with the noun spelled
   * out. A fixed set rather than free text: every noun needs its own plural
   * forms in each locale, so it cannot be supplied by the caller.
   */
  noun?: "tool";
}

export default function EnabledCount({
  noun,
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
        noun === "tool"
          ? t.rich("enabledCount.tools", {
              enabled: enabledCount,
              total: totalCount,
              value,
            })
          : t.rich("enabledCount.label", {
              enabled: enabledCount,
              total: totalCount,
              value,
            })
      )}
    </Text>
  );
}
