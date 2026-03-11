import type { Meta, StoryObj } from "@storybook/react";
import EmptyMessage from "./EmptyMessage";
import { SvgFileText, SvgUsers } from "@opal/icons";

const meta: Meta<typeof EmptyMessage> = {
  title: "refresh-components/messages/EmptyMessage",
  component: EmptyMessage,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof EmptyMessage>;

export const Default: Story = {
  args: {
    title: "No items found",
  },
};

export const WithDescription: Story = {
  args: {
    title: "No connectors configured",
    description:
      "Set up a connector to start indexing documents from your data sources.",
  },
};

export const WithCustomIcon: Story = {
  args: {
    icon: SvgFileText,
    title: "No documents available",
    description: "Upload documents or connect a data source to get started.",
  },
};

export const UsersEmpty: Story = {
  args: {
    icon: SvgUsers,
    title: "No users in this group",
    description: "Add users to this group to grant them access.",
  },
};
