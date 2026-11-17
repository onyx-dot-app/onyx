"use client";

import React, { useState } from "react";
import { Presence } from "@opal/components";
import { Section } from "@opal/layouts";
import { cn } from "@opal/utils";
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
}

export interface ResponseProps {
  items: ResponseItem[];
}

/**
 * A response's layout, the same in chat and Craft: its items in arrival order,
 * 0.75rem apart, with text lined up with the run header's text.
 *
 * An item that arrives after the response first renders opens its space:
 * its height (and the 0.75rem after it) grows, then it fades in, so whatever
 * sits below slides down instead of snapping. Run cards do this themselves
 * (`RunCard`). Items present on the first render, such as saved history,
 * appear at once.
 */
export function Response({ items }: ResponseProps) {
  const [initialKeys] = useState(() => new Set(items.map((item) => item.key)));

  return (
    <Section alignItems="stretch" gap={0} height="auto">
      {items.map((item, index) => {
        // The gap sits below each item but the last, inside its wrapper, so
        // it opens with the item. Below rather than above: text that arrives
        // above a card brings its gap with it, and the card does not move.
        const spaced = index < items.length - 1 ? "pb-3" : undefined;
        if (item.kind === "run") {
          return (
            <div key={item.key} className={spaced}>
              {item.node}
            </div>
          );
        }
        return (
          <Presence key={item.key} appear={!initialKeys.has(item.key)} grow>
            <div className={cn(spaced)}>
              {item.kind === "text" ? (
                <AnswerText>{item.node}</AnswerText>
              ) : (
                item.node
              )}
            </div>
          </Presence>
        );
      })}
    </Section>
  );
}

export default Response;
