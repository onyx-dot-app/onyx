import React from "react";
import { z } from "zod";
import { defineComponent } from "@onyx/genui";
import PreviewImage from "@/refresh-components/PreviewImage";

export const imageComponent = defineComponent({
  name: "Image",
  description: "Displays an image",
  group: "Content",
  props: z.object({
    src: z.string().describe("Image URL"),
    alt: z.string().optional().describe("Alt text for accessibility"),
    width: z.string().optional().describe("CSS width"),
    height: z.string().optional().describe("CSS height"),
  }),
  component: ({
    props,
  }: {
    props: {
      src: string;
      alt?: string;
      width?: string;
      height?: string;
    };
  }) => (
    <PreviewImage
      src={props.src}
      alt={props.alt ?? ""}
      className={
        [
          props.width ? `w-[${props.width}]` : undefined,
          props.height ? `h-[${props.height}]` : undefined,
        ]
          .filter(Boolean)
          .join(" ") || undefined
      }
    />
  ),
});
