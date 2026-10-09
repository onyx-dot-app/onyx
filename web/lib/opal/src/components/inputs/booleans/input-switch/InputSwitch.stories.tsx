import type { Meta, StoryObj } from "@storybook/react-vite";
import { InputSwitch } from "./components";

const meta: Meta<typeof InputSwitch> = {
  title: "opal/Inputs/InputSwitch",
  component: InputSwitch,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof InputSwitch>;

export const Default: Story = {
  args: {},
};

export const Checked: Story = {
  args: {
    checked: true,
  },
};

export const Unchecked: Story = {
  args: {
    checked: false,
  },
};

export const Disabled: Story = {
  args: {
    disabled: true,
  },
};

export const DisabledChecked: Story = {
  args: {
    disabled: true,
    checked: true,
  },
};

export const DefaultChecked: Story = {
  args: {
    defaultChecked: true,
  },
};
