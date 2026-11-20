"use client";

import type { ReactNode } from "react";
import { Section } from "@opal/layouts/general/components";

interface ToolbarProps {
  /** The search field. It takes most of the row. */
  search: ReactNode;
  /** Filter inputs after the search field, each with a `key`. */
  filters?: ReactNode[];
  /** Controls at the end of the row, such as bulk actions. They keep their width. */
  actions?: ReactNode;
}

/** A row of a search field, filters and actions above a list or table. On a
 * narrow page the items wrap to new lines. */
function Toolbar({ search, filters = [], actions }: ToolbarProps) {
  return (
    <Section flexDirection="row" alignItems="center" height="auto" gap={2} wrap>
      <Section height="auto" alignItems="stretch" grow={3} basis={16}>
        {search}
      </Section>
      {filters.map((filter, index) => (
        <Section
          key={index}
          height="auto"
          alignItems="stretch"
          grow={1}
          basis={12}
        >
          {filter}
        </Section>
      ))}
      {actions && (
        <Section
          flexDirection="row"
          alignItems="center"
          width="auto"
          height="auto"
          gap={2}
          shrink={false}
        >
          {actions}
        </Section>
      )}
    </Section>
  );
}

export { Toolbar, type ToolbarProps };
