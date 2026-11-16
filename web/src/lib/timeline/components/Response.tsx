import React from "react";
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
}

export interface ResponseProps {
  items: ResponseItem[];
}

/**
 * A response's layout, the same in chat and Craft: its items in arrival order,
 * 0.75rem apart, with text lined up with the run header's text.
 */
export function Response({ items }: ResponseProps) {
  return (
    <Section alignItems="stretch" gap={3} height="auto">
      {items.map((item) =>
        item.kind === "text" ? (
          <AnswerText key={item.key}>{item.node}</AnswerText>
        ) : (
          <React.Fragment key={item.key}>{item.node}</React.Fragment>
        )
      )}
    </Section>
  );
}

export default Response;
