import type { Meta, StoryObj } from "@storybook/react";
import { IllustrationContent } from "@opal/layouts";
import { SvgEmpty } from "@opal/illustrations";

const meta = {
  title: "Layouts/IllustrationContent",
  component: IllustrationContent,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
} satisfies Meta<typeof IllustrationContent>;

export default meta;

type Story = StoryObj<typeof meta>;

// ---------------------------------------------------------------------------
// Stories
// ---------------------------------------------------------------------------

export const Default: Story = {
  args: {
    illustration: SvgEmpty,
    title: "No results found",
    description: "Try adjusting your search or filters to find what you need.",
  },
};

export const TitleOnly: Story = {
  args: {
    title: "Nothing here yet",
  },
};

export const NoIllustration: Story = {
  args: {
    title: "No documents available",
    description:
      "Connect a data source to start indexing documents into your workspace.",
  },
};
