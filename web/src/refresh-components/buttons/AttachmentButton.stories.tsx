import type { Meta, StoryObj } from "@storybook/react";
import AttachmentButton from "./AttachmentButton";
import { SvgTextLines, SvgTrash, SvgFiles } from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof AttachmentButton> = {
  title: "refresh-components/buttons/AttachmentButton",
  component: AttachmentButton,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <div style={{ width: 400 }}>
          <Story />
        </div>
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof AttachmentButton>;

export const Default: Story = {
  args: {
    icon: SvgTextLines,
    children: "Project Proposal",
    description: "document.pdf",
    rightText: "2.4 MB",
  },
};

export const Selected: Story = {
  args: {
    icon: SvgTextLines,
    children: "Project Proposal",
    description: "document.pdf",
    rightText: "2.4 MB",
    selected: true,
  },
};

export const Processing: Story = {
  args: {
    icon: SvgTextLines,
    children: "Project Proposal",
    description: "Uploading...",
    rightText: "45%",
    processing: true,
  },
};

export const WithViewButton: Story = {
  args: {
    icon: SvgTextLines,
    children: "Project Proposal",
    description: "document.pdf",
    rightText: "2.4 MB",
    onView: () => {},
  },
};

export const WithActionButton: Story = {
  args: {
    icon: SvgTextLines,
    children: "Project Proposal",
    description: "document.pdf",
    rightText: "2.4 MB",
    actionIcon: SvgTrash,
    onAction: () => {},
  },
};

export const FileList: Story = {
  render: () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <AttachmentButton
        icon={SvgTextLines}
        description="proposal.pdf"
        rightText="2.4 MB"
        onView={() => {}}
      >
        Project Proposal
      </AttachmentButton>
      <AttachmentButton
        icon={SvgFiles}
        description="report.xlsx"
        rightText="1.1 MB"
        selected
      >
        Quarterly Report
      </AttachmentButton>
      <AttachmentButton
        icon={SvgTextLines}
        description="Uploading..."
        rightText="72%"
        processing
      >
        Meeting Notes
      </AttachmentButton>
      <AttachmentButton
        icon={SvgFiles}
        description="readme.md"
        rightText="4 KB"
        actionIcon={SvgTrash}
        onAction={() => {}}
      >
        README
      </AttachmentButton>
    </div>
  ),
};
