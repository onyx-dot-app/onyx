import type { Meta, StoryObj } from "@storybook/react";
import InputNumber from "./InputNumber";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof InputNumber> = {
  title: "refresh-components/inputs/InputNumber",
  component: InputNumber,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <div style={{ width: 200 }}>
          <Story />
        </div>
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof InputNumber>;

export const Default: Story = {
  args: {
    value: 5,
    onChange: () => {},
  },
};

export const WithMinMax: Story = {
  args: {
    value: 50,
    onChange: () => {},
    min: 0,
    max: 100,
  },
};

export const WithReset: Story = {
  args: {
    value: 42,
    onChange: () => {},
    showReset: true,
    defaultValue: 10,
  },
};
