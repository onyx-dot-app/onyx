import type { Meta, StoryObj } from "@storybook/react-vite";
import InputNumber from "@opal/components/inputs/input-number/components";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof InputNumber> = {
  title: "opal/components/InputNumber",
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
