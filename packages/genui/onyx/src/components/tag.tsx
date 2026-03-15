import React from "react";
import { z } from "zod";
import { defineComponent } from "@onyx/genui";
import { Tag } from "@opal/components";

export const tagComponent = defineComponent({
  name: "Tag",
  description: "A small label tag with color",
  group: "Content",
  props: z.object({
    title: z.string().describe("Tag text"),
    color: z
      .enum(["green", "purple", "blue", "gray", "amber"])
      .optional()
      .describe("Tag color"),
    size: z.enum(["sm", "md"]).optional().describe("Tag size"),
  }),
  component: ({
    props,
  }: {
    props: {
      title: string;
      color?: "green" | "purple" | "blue" | "gray" | "amber";
      size?: "sm" | "md";
    };
  }) => <Tag title={props.title} color={props.color} size={props.size} />,
});
