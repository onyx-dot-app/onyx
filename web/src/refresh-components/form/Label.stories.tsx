import type { Meta, StoryObj } from "@storybook/react";
import Label from "./Label";

const meta: Meta<typeof Label> = {
  title: "refresh-components/form/Label",
  component: Label,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Label>;

export const Default: Story = {
  args: {
    children: "Email Address",
    name: "email",
  },
};

export const Disabled: Story = {
  args: {
    children: "Disabled Label",
    name: "disabled-input",
    disabled: true,
  },
};
