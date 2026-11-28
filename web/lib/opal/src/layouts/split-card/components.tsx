"use client";

import type { ReactNode } from "react";
import { Card } from "@opal/components";
import { Section } from "@opal/layouts/general/components";

interface SplitCardProps {
  /** The narrow pane at the start, such as a list of files. */
  aside: ReactNode;
  /** The wide pane, such as a viewer of the selected item. */
  children: ReactNode;
  /** Minimum height of the card, in rem. */
  minHeight?: number;
}

/** A bordered card in two panes: a narrow aside beside a wide main pane. */
function SplitCard({ aside, children, minHeight }: SplitCardProps) {
  return (
    <Card border="solid" rounding={4} padding={0}>
      <Section
        flexDirection="row"
        alignItems="stretch"
        height="auto"
        gap={0}
        minHeight={minHeight}
      >
        <Section
          justifyContent="between"
          alignItems="stretch"
          width="auto"
          height="auto"
          gap={1}
          padding={1}
          className="basis-56 border-e border-border-01 max-sm:basis-40"
        >
          {aside}
        </Section>
        <Section
          justifyContent="start"
          alignItems="stretch"
          height="auto"
          gap={2}
          padding={2}
          grow={1}
        >
          {children}
        </Section>
      </Section>
    </Card>
  );
}

export { SplitCard, type SplitCardProps };
