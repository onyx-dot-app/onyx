import React from "react";
import { z } from "zod";
import { defineComponent } from "@onyx/genui";
import Separator from "@/refresh-components/Separator";

export const dividerComponent = defineComponent({
  name: "Divider",
  description: "A horizontal separator line",
  group: "Layout",
  props: z.object({
    spacing: z
      .enum(["sm", "md", "lg"])
      .optional()
      .describe("Vertical spacing around the divider"),
  }),
  component: ({ props }: { props: { spacing?: string } }) => (
    <Separator noPadding={props.spacing === "sm"} />
  ),
});
