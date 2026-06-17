import type { Meta, StoryObj } from "@storybook/react";
import WebSearchBody from "@/app/craft/components/tool-cards/WebSearchBody";
import type { ToolCallState } from "@/app/craft/types/displayTypes";

const meta: Meta<typeof WebSearchBody> = {
  title: "Apps/Craft/Tool Cards/Web Search Body",
  component: WebSearchBody,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <div className="w-[640px]">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof WebSearchBody>;

function websearch(overrides: Partial<ToolCallState>): ToolCallState {
  return {
    id: "websearch-1",
    kind: "other",
    toolName: "websearch",
    title: "Searching the web",
    description: "",
    command: "",
    status: "completed",
    rawOutput: "",
    ...overrides,
  };
}

export const StructuredResults: Story = {
  args: {
    toolCall: websearch({
      description: "tailwind v4 wrap-break-word",
      rawOutput: `## Overflow wrap - Tailwind CSS
https://tailwindcss.com/docs/overflow-wrap
Utilities for controlling how words break inside an element. wrap-break-word maps to overflow-wrap: break-word.

## Tailwind v4 upgrade guide
https://tailwindcss.com/docs/upgrade-guide
The v4 release renamed several utilities including break-words to wrap-break-word for consistency with the underlying CSS property names.

## Discussion: break-words removed in v4
https://github.com/tailwindlabs/tailwindcss/discussions/13456
Several projects hit this on upgrade. Replace break-words with wrap-break-word — same CSS, new utility name.`,
    }),
  },
};

export const TitlesOnly: Story = {
  args: {
    toolCall: websearch({
      description: "React 19 release notes",
      rawOutput: `## React 19 is now stable
https://react.dev/blog/2024/12/05/react-19

## React Server Components — production guide
https://react.dev/reference/rsc/server-components

## Migrating from React 18 to 19
https://react.dev/blog/2024/04/25/react-19-upgrade-guide`,
    }),
  },
};

export const RawFallback: Story = {
  args: {
    toolCall: websearch({
      description: "unstructured query",
      rawOutput:
        "Search returned no parseable results, but the agent received this text dump for context.\nIt may contain useful information for the next turn.",
    }),
  },
};

export const NoResults: Story = {
  args: {
    toolCall: websearch({
      description: "xyzzy-nothing-here",
      rawOutput: "",
    }),
  },
};
