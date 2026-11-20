"use client";

import React, { useState } from "react";
import { Presence } from "@opal/components";
import { Section } from "@opal/layouts";
import { AnswerText } from "@/lib/timeline/components/AnswerText";

/**
 * One item of a response, in arrival order. A `run` is a run card, `text` is
 * answer text (or anything that lines up with it, such as the cursor), and a
 * `card` is a block such as a notice or an approval card.
 */
export interface ResponseItem {
  kind: "run" | "text" | "card";
  key: React.Key;
  node: React.ReactNode;
  /**
   * Play the entry even when the item is present on the first render. Unset,
   * only items that arrive later play it.
   */
  appear?: boolean;
}

export interface ResponseProps {
  items: ResponseItem[];
}

/**
 * A response's layout, the same in chat and Craft: its items in arrival order,
 * 0.75rem apart, with text lined up with the run header's text.
 *
 * The spacing is the column's gap, so an item that renders nothing (a hidden
 * run) takes no space. An item that arrives after the response first renders
 * opens its space: its height grows, then it fades in, so whatever sits below
 * slides down instead of snapping. Run cards do this themselves (`RunCard`).
 * Items present on the first render, such as saved history, appear at once.
 */
export function Response({ items }: ResponseProps) {
  const [initialKeys] = useState(() => new Set(items.map((item) => item.key)));

  return (
    <Section alignItems="stretch" gap={3} height="auto">
      {items.map((item) =>
        item.kind === "run" ? (
          <React.Fragment key={item.key}>{item.node}</React.Fragment>
        ) : (
          <Presence
            key={item.key}
            appear={item.appear ?? !initialKeys.has(item.key)}
            grow
          >
            {item.kind === "text" ? (
              <AnswerText>{item.node}</AnswerText>
            ) : (
              item.node
            )}
          </Presence>
        )
      )}
    </Section>
  );
}

export default Response;
