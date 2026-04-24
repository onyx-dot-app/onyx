import type { Meta, StoryObj } from "@storybook/react";
import { Checkbox } from "@opal/components/checkbox/components";
import { Text } from "@opal/components/text/components";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta = {
  title: "Components/Checkbox",
  component: Checkbox,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <Story />
      </TooltipPrimitive.Provider>
    ),
  ],
} satisfies Meta<typeof Checkbox>;

export default meta;

type Story = StoryObj<typeof meta>;

// ---------------------------------------------------------------------------
// Basic states
// ---------------------------------------------------------------------------

export const Default: Story = {
  args: {},
};

export const Checked: Story = {
  args: {
    checked: true,
  },
};

export const Indeterminate: Story = {
  args: {
    indeterminate: true,
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

// ---------------------------------------------------------------------------
// With label
// ---------------------------------------------------------------------------

export const WithLabel: StoryObj = {
  render: () => (
    <div className="flex items-center gap-2">
      <Checkbox id="terms" />
      <label htmlFor="terms" className="cursor-pointer">
        <Text font="main-ui-body" color="text-04">
          Accept terms and conditions
        </Text>
      </label>
    </div>
  ),
};

// ---------------------------------------------------------------------------
// All states side-by-side
// ---------------------------------------------------------------------------

export const AllStates: StoryObj = {
  render: () => (
    <div className="flex flex-col gap-4">
      {(
        [
          ["Unchecked", {}],
          ["Checked", { checked: true }],
          ["Indeterminate", { indeterminate: true }],
          ["Disabled", { disabled: true }],
          ["Disabled + Checked", { disabled: true, checked: true }],
          ["Disabled + Indeterminate", { disabled: true, indeterminate: true }],
        ] as const
      ).map(([label, props]) => (
        <div key={label} className="flex items-center gap-3">
          <Checkbox {...props} />
          <Text font="secondary-body" color="text-03">
            {label}
          </Text>
        </div>
      ))}
    </div>
  ),
};
