import React from "react";
import { z } from "zod";
import { defineComponent } from "@onyx/genui";
import Card from "@/refresh-components/cards/Card";
import Text from "@/refresh-components/texts/Text";

export const cardComponent = defineComponent({
  name: "Card",
  description: "A container card with optional title and padding",
  group: "Layout",
  props: z.object({
    title: z.string().optional().describe("Card heading"),
    padding: z
      .enum(["none", "sm", "md", "lg"])
      .optional()
      .describe("Inner padding"),
  }),
  component: ({
    props,
    children,
  }: {
    props: { title?: string; padding?: string };
    children?: React.ReactNode;
  }) => (
    <Card variant="primary">
      {props.title && (
        <Text headingH3 text05>
          {props.title}
        </Text>
      )}
      {children}
    </Card>
  ),
});
