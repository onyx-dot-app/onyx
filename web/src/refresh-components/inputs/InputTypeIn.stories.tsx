import type { Meta, StoryObj } from "@storybook/react";
import InputTypeIn from "./InputTypeIn";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof InputTypeIn> = {
  title: "refresh-components/inputs/InputTypeIn",
  component: InputTypeIn,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <div style={{ width: 320 }}>
          <Story />
        </div>
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof InputTypeIn>;

export const Default: Story = {
  args: {
    placeholder: "Enter text...",
  },
};

export const WithPrefix: Story = {
  args: {
    prefixText: "https://",
    placeholder: "example.com",
  },
};

export const WithSearchIcon: Story = {
  args: {
    leftSearchIcon: true,
    placeholder: "Search...",
  },
};

export const WithClearButton: Story = {
  args: {
    showClearButton: true,
    value: "Some text to clear",
    onChange: () => {},
  },
};

export const Disabled: Story = {
  args: {
    variant: "disabled",
    value: "Cannot edit",
  },
};

export const Error: Story = {
  args: {
    variant: "error",
    value: "Invalid input",
    placeholder: "Enter text...",
  },
};

export const ReadOnly: Story = {
  args: {
    variant: "readOnly",
    value: "Read-only value",
  },
};
