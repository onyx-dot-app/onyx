import type { Meta, StoryObj } from "@storybook/react";
import Attachment from "./Attachment";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof Attachment> = {
  title: "refresh-components/Attachment",
  component: Attachment,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
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
type Story = StoryObj<typeof Attachment>;

export const Default: Story = {
  args: {
    fileName: "quarterly-report.pdf",
  },
};

export const WithOpenAction: Story = {
  args: {
    fileName: "meeting-notes.docx",
    open: () => alert("Opening document"),
  },
};

export const LongFileName: Story = {
  args: {
    fileName:
      "very-long-document-name-that-might-overflow-the-container-2024-Q4-final-draft.pdf",
  },
};
