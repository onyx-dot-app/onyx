import type { Meta, StoryObj } from "@storybook/react";
import { ContentAction } from "@opal/layouts";
import { Button } from "@opal/components";
import { SvgSettings } from "@opal/icons";

const meta = {
  title: "Layouts/ContentAction",
  component: ContentAction,
  tags: ["autodocs"],

  parameters: {
    layout: "centered",
  },
} satisfies Meta<typeof ContentAction>;

export default meta;

type Story = StoryObj<typeof meta>;

// ---------------------------------------------------------------------------
// Stories
// ---------------------------------------------------------------------------

export const Default: Story = {
  args: {
    sizePreset: "main-content",
    variant: "section",
    title: "OpenAI",
    description: "GPT-4o language model provider.",
    icon: SvgSettings,
    rightChildren: <Button prominence="tertiary">Edit</Button>,
  },
};

export const MultipleActions: Story = {
  args: {
    sizePreset: "main-content",
    variant: "section",
    title: "Connector",
    description: "Manage your data source connector.",
    rightChildren: (
      <div className="flex items-center gap-2">
        <Button prominence="tertiary" icon={SvgSettings} />
        <Button variant="danger" prominence="primary">
          Delete
        </Button>
      </div>
    ),
  },
};

export const NoPadding: Story = {
  args: {
    sizePreset: "main-content",
    variant: "section",
    title: "Compact Row",
    description: "No padding around content area.",
    padding: "fit",
    rightChildren: <Button prominence="tertiary">Action</Button>,
  },
};
