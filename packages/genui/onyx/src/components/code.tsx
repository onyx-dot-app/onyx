import React from "react";
import { z } from "zod";
import { defineComponent } from "@onyx/genui";
import Code from "@/refresh-components/Code";

export const codeComponent = defineComponent({
  name: "Code",
  description: "A code block with optional copy button",
  group: "Content",
  props: z.object({
    children: z.string().describe("The code content"),
    language: z
      .string()
      .optional()
      .describe("Programming language for syntax highlighting"),
    showCopyButton: z
      .boolean()
      .optional()
      .describe("Show copy-to-clipboard button"),
  }),
  component: ({
    props,
  }: {
    props: {
      children: string;
      language?: string;
      showCopyButton?: boolean;
    };
  }) => <Code showCopyButton={props.showCopyButton}>{props.children}</Code>,
});
