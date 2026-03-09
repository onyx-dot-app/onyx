import React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import Calendar from "./Calendar";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type { DateRange } from "react-day-picker";

const meta: Meta<typeof Calendar> = {
  title: "refresh-components/Calendar",
  component: Calendar,
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
};

export default meta;
type Story = StoryObj<typeof Calendar>;

// ---------------------------------------------------------------------------
// Single selection
// ---------------------------------------------------------------------------

function SingleSelectDemo() {
  const [selected, setSelected] = React.useState<Date | undefined>(new Date());
  return <Calendar mode="single" selected={selected} onSelect={setSelected} />;
}

export const SingleSelect: Story = {
  render: () => <SingleSelectDemo />,
};

// ---------------------------------------------------------------------------
// Range selection
// ---------------------------------------------------------------------------

function RangeSelectDemo() {
  const [range, setRange] = React.useState<DateRange | undefined>({
    from: new Date(2025, 2, 10),
    to: new Date(2025, 2, 20),
  });
  return <Calendar mode="range" selected={range} onSelect={setRange} />;
}

export const RangeSelect: Story = {
  render: () => <RangeSelectDemo />,
};

// ---------------------------------------------------------------------------
// Without outside days
// ---------------------------------------------------------------------------

export const NoOutsideDays: Story = {
  args: {
    mode: "single",
    showOutsideDays: false,
  },
};
