import React from "react";
import { z } from "zod";
import { defineComponent } from "@onyx/genui";
import Text from "@/refresh-components/texts/Text";

export const listComponent = defineComponent({
  name: "List",
  description: "An ordered or unordered list",
  group: "Content",
  props: z.object({
    items: z.array(z.string()).describe("List item texts"),
    ordered: z
      .boolean()
      .optional()
      .describe("Use numbered list instead of bullets"),
  }),
  component: ({
    props,
  }: {
    props: {
      items: string[];
      ordered?: boolean;
    };
  }) => {
    const Tag = props.ordered ? "ol" : "ul";

    return (
      <Tag
        className={
          props.ordered
            ? "list-decimal pl-6 space-y-1"
            : "list-disc pl-6 space-y-1"
        }
      >
        {(props.items ?? []).map((item, i) => (
          <li key={i}>
            <Text mainContentBody text05 as="span">
              {item}
            </Text>
          </li>
        ))}
      </Tag>
    );
  },
});
