import React from "react";
import { z } from "zod";
import { defineComponent } from "@onyx/genui";
import InlineExternalLink from "@/refresh-components/InlineExternalLink";
import Text from "@/refresh-components/texts/Text";

export const linkComponent = defineComponent({
  name: "Link",
  description: "A clickable hyperlink",
  group: "Content",
  props: z.object({
    children: z.string().describe("Link text"),
    href: z.string().describe("URL to link to"),
    external: z.boolean().optional().describe("Open in new tab"),
  }),
  component: ({
    props,
  }: {
    props: {
      children: string;
      href: string;
      external?: boolean;
    };
  }) => {
    if (props.external !== false) {
      return (
        <InlineExternalLink href={props.href}>
          <Text mainContentBody text05 as="span" className="underline">
            {props.children}
          </Text>
        </InlineExternalLink>
      );
    }

    return (
      <a href={props.href} className="underline">
        <Text mainContentBody text05 as="span" className="underline">
          {props.children}
        </Text>
      </a>
    );
  },
});
