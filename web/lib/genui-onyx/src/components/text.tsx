import React from "react";
import { z } from "zod";
import { defineComponent } from "@onyx/genui";
import Text from "@/refresh-components/texts/Text";

export const textComponent = defineComponent({
  name: "Text",
  description: "Displays text with typography variants",
  group: "Content",
  props: z.object({
    children: z.string().describe("The text content"),
    headingH1: z.boolean().optional().describe("Heading level 1"),
    headingH2: z.boolean().optional().describe("Heading level 2"),
    headingH3: z.boolean().optional().describe("Heading level 3"),
    muted: z.boolean().optional().describe("Muted/secondary style"),
    mono: z.boolean().optional().describe("Monospace font"),
    bold: z.boolean().optional().describe("Bold emphasis"),
  }),
  component: ({
    props,
  }: {
    props: {
      children: string;
      headingH1?: boolean;
      headingH2?: boolean;
      headingH3?: boolean;
      muted?: boolean;
      mono?: boolean;
      bold?: boolean;
    };
  }) => {
    const as = props.headingH1
      ? ("p" as const)
      : props.headingH2
        ? ("p" as const)
        : props.headingH3
          ? ("p" as const)
          : ("span" as const);

    return (
      <Text
        as={as}
        headingH1={props.headingH1}
        headingH2={props.headingH2}
        headingH3={props.headingH3}
        mainContentMuted={props.muted}
        mainContentMono={props.mono}
        mainContentEmphasis={props.bold}
        mainContentBody={
          !props.headingH1 &&
          !props.headingH2 &&
          !props.headingH3 &&
          !props.muted &&
          !props.mono &&
          !props.bold
        }
        text05
      >
        {props.children}
      </Text>
    );
  },
});
