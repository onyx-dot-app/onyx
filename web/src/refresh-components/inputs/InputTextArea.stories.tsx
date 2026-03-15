import type { Meta, StoryObj } from "@storybook/react";
import InputTextArea from "./InputTextArea";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof InputTextArea> = {
  title: "refresh-components/inputs/InputTextArea",
  component: InputTextArea,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <div style={{ width: 400 }}>
          <Story />
        </div>
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof InputTextArea>;

export const Default: Story = {
  args: {
    placeholder: "Enter a description...",
  },
};

export const AutoResize: Story = {
  args: {
    autoResize: true,
    placeholder: "This textarea grows as you type...",
  },
};

export const WithMaxRows: Story = {
  args: {
    autoResize: true,
    maxRows: 5,
    placeholder: "Grows up to 5 rows...",
  },
};

export const Error: Story = {
  args: {
    variant: "error",
    value: "Invalid content",
    placeholder: "Enter a description...",
  },
};

export const Disabled: Story = {
  args: {
    variant: "disabled",
    value: "Cannot edit this textarea",
  },
};

export const ReadOnly: Story = {
  args: {
    variant: "readOnly",
    value: "This content is read-only and cannot be modified.",
  },
};

export const NonResizable: Story = {
  args: {
    resizable: false,
    placeholder: "This textarea cannot be resized...",
  },
};
