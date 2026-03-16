import React from "react";
import { z } from "zod";
import { defineComponent } from "@onyx/genui";
import { Tag } from "@opal/components";

const VALID_TAG_COLORS = new Set<string>([
  "green",
  "purple",
  "blue",
  "gray",
  "amber",
]);

type TagColor = "green" | "purple" | "blue" | "gray" | "amber";

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
      color?: string;
      size?: "sm" | "md";
    };
  }) => {
    const safeColor: TagColor =
      props.color && VALID_TAG_COLORS.has(props.color)
        ? (props.color as TagColor)
        : "gray";

    return (
      <Tag title={props.title ?? ""} color={safeColor} size={props.size} />
    );
  },
});
