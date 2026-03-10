import type { Meta, StoryObj } from "@storybook/react";
import SimpleLoader from "./SimpleLoader";

const meta: Meta<typeof SimpleLoader> = {
  title: "refresh-components/loaders/SimpleLoader",
  component: SimpleLoader,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof SimpleLoader>;

export const Default: Story = {
  args: {},
};

export const Large: Story = {
  args: {
    className: "h-8 w-8",
  },
};

export const CustomColor: Story = {
  args: {
    className: "h-6 w-6 stroke-text-05",
  },
};
