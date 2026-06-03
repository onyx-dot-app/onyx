import type { Meta, StoryObj } from "@storybook/react";
import SvgSimpleLoader from "@opal/icons/simple-loader";

const meta: Meta<typeof SvgSimpleLoader> = {
  title: "opal/icons/SimpleLoader",
  component: SvgSimpleLoader,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof SvgSimpleLoader>;

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
