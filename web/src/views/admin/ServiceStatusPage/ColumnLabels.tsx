"use client";

import type { RichStr } from "@opal/types";
import { Spacer, Text } from "@opal/components";
import { Section } from "@opal/layouts";

// A row card's padding (3, 0.75rem) plus its 1px border, so each label sits
// above the column it names.
const ROW_INSET_REM = 0.8125;

interface ColumnLabelsProps {
  title: string | RichStr;
  labels: [string | RichStr, string | RichStr];
}

/** The heading of a list of row cards, with the column labels on its grid. */
export default function ColumnLabels({ title, labels }: ColumnLabelsProps) {
  return (
    <Section flexDirection="row" gap={0} width="full" padding={0}>
      <Spacer orientation="horizontal" rem={ROW_INSET_REM} />
      {/* Bottom-aligned, so the larger title and the labels share a baseline. */}
      <Section
        flexDirection="row"
        gap={2}
        alignItems="end"
        width="full"
        padding={0}
      >
        <Section alignItems="start" width="full" padding={0}>
          <Text font="main-ui-action" color="text-03" as="h3">
            {title}
          </Text>
        </Section>
        {labels.map((label, index) => (
          <Section key={index} alignItems="start" width="full" padding={0}>
            <Text as="p" font="secondary-body" color="text-03">
              {label}
            </Text>
          </Section>
        ))}
      </Section>
      <Spacer orientation="horizontal" rem={ROW_INSET_REM} />
    </Section>
  );
}
