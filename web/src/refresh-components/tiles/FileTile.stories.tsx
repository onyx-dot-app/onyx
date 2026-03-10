import type { Meta, StoryObj } from "@storybook/react";
import FileTile from "./FileTile";
import { SvgTextLines, SvgFiles } from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof FileTile> = {
  title: "refresh-components/tiles/FileTile",
  component: FileTile,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <div style={{ maxWidth: 300 }}>
          <Story />
        </div>
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof FileTile>;

export const Default: Story = {
  args: {
    title: "document.pdf",
    description: "Project proposal document",
    icon: SvgTextLines,
  },
};

export const WithOpen: Story = {
  args: {
    title: "report.xlsx",
    description: "Quarterly report",
    icon: SvgFiles,
    onOpen: () => {},
  },
};

export const WithRemove: Story = {
  args: {
    title: "notes.md",
    description: "Meeting notes",
    icon: SvgTextLines,
    onRemove: () => {},
  },
};

export const Processing: Story = {
  args: {
    title: "uploading.pdf",
    description: "Processing...",
    icon: SvgTextLines,
    state: "processing",
  },
};

export const Disabled: Story = {
  args: {
    title: "locked.pdf",
    description: "Access denied",
    icon: SvgFiles,
    state: "disabled",
  },
};

export const TitleOnly: Story = {
  args: {
    title: "image.png",
    icon: SvgFiles,
  },
};

export const DefaultIcon: Story = {
  args: {
    title: "unknown-file",
    description: "Uses default text lines icon",
  },
};

export const FileList: Story = {
  render: () => (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
      <FileTile
        title="proposal.pdf"
        description="2.4 MB"
        icon={SvgTextLines}
        onOpen={() => {}}
        onRemove={() => {}}
      />
      <FileTile
        title="report.xlsx"
        description="1.1 MB"
        icon={SvgFiles}
        onOpen={() => {}}
      />
      <FileTile
        title="uploading.doc"
        description="Processing..."
        icon={SvgTextLines}
        state="processing"
      />
      <FileTile
        title="locked.pdf"
        description="No access"
        icon={SvgFiles}
        state="disabled"
      />
    </div>
  ),
};
