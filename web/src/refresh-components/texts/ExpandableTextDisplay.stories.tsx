import type { Meta, StoryObj } from "@storybook/react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import ExpandableTextDisplay from "./ExpandableTextDisplay";

const meta: Meta<typeof ExpandableTextDisplay> = {
  title: "refresh-components/texts/ExpandableTextDisplay",
  component: ExpandableTextDisplay,
  tags: ["autodocs"],
  parameters: {
    layout: "padded",
  },
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <Story />
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof ExpandableTextDisplay>;

const shortContent =
  "This is a short piece of content that fits within the default line clamp.";

const longContent = Array.from(
  { length: 30 },
  (_, i) =>
    `Line ${i + 1}: Lorem ipsum dolor sit amet, consectetur adipiscing elit.`
).join("\n");

export const ShortContent: Story = {
  args: {
    title: "Short Content",
    content: shortContent,
  },
};

export const LongContent: Story = {
  args: {
    title: "Log Output",
    content: longContent,
  },
};

export const CustomMaxLines: Story = {
  args: {
    title: "Compact View",
    content: longContent,
    maxLines: 3,
  },
};

export const WithSubtitle: Story = {
  args: {
    title: "Build Log",
    content: longContent,
    subtitle: "2.4 KB - 30 lines",
  },
};

export const StreamingMode: Story = {
  args: {
    title: "Live Output",
    content: longContent,
    isStreaming: true,
    maxLines: 5,
  },
};

export const WithCustomRenderer: Story = {
  args: {
    title: "Formatted Content",
    content:
      "# Hello World\n\nThis is **bold** and this is *italic*.\n\n- Item 1\n- Item 2\n- Item 3",
    renderContent: (content: string) => (
      <pre
        style={{
          whiteSpace: "pre-wrap",
          fontFamily: "monospace",
          fontSize: 13,
        }}
      >
        {content}
      </pre>
    ),
  },
};
