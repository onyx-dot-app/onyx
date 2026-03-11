import type { Meta, StoryObj } from "@storybook/react";
import EnabledCount from "./EnabledCount";

const meta: Meta<typeof EnabledCount> = {
  title: "refresh-components/EnabledCount",
  component: EnabledCount,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
};

export default meta;
type Story = StoryObj<typeof EnabledCount>;

export const Default: Story = {
  args: {
    enabledCount: 5,
    totalCount: 12,
  },
};

export const WithName: Story = {
  args: {
    name: "connector",
    enabledCount: 3,
    totalCount: 10,
  },
};

export const AllEnabled: Story = {
  args: {
    name: "source",
    enabledCount: 8,
    totalCount: 8,
  },
};

export const NoneEnabled: Story = {
  args: {
    name: "item",
    enabledCount: 0,
    totalCount: 15,
  },
};

export const SingleItem: Story = {
  args: {
    name: "document",
    enabledCount: 1,
    totalCount: 1,
  },
};
