import type { Meta, StoryObj } from "@storybook/react-vite";
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

export const WithNoun: Story = {
  args: {
    noun: "tool",
    enabledCount: 3,
    totalCount: 10,
  },
};

export const AllEnabled: Story = {
  args: {
    noun: "tool",
    enabledCount: 8,
    totalCount: 8,
  },
};

export const NoneEnabled: Story = {
  args: {
    noun: "tool",
    enabledCount: 0,
    totalCount: 15,
  },
};

/** The singular branch of the plural: "1 of 1 tool", not "tools". */
export const SingleItem: Story = {
  args: {
    noun: "tool",
    enabledCount: 1,
    totalCount: 1,
  },
};
