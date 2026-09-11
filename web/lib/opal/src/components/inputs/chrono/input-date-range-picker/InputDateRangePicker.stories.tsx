import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import {
  InputDateRangePicker,
  type DateRange,
} from "@opal/components/inputs/chrono/input-date-range-picker/components";

const meta: Meta<typeof InputDateRangePicker> = {
  title: "components/InputDateRangePicker",
  component: InputDateRangePicker,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
  decorators: [
    (Story) => (
      <div className="min-h-[640px] min-w-[760px] bg-background-neutral-00 p-8">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof InputDateRangePicker>;

function ControlledRange({ initialValue }: { initialValue: DateRange }) {
  const [value, setValue] = useState<DateRange>(initialValue);

  return <InputDateRangePicker value={value} onValueChange={setValue} />;
}

export const Default: Story = {
  render: () => (
    <ControlledRange
      initialValue={{
        from: new Date(2026, 6, 5),
        to: new Date(2026, 7, 4),
      }}
    />
  ),
};

export const ShortCustomRange: Story = {
  render: () => (
    <ControlledRange
      initialValue={{
        from: new Date(2026, 7, 2),
        to: new Date(2026, 7, 4),
      }}
    />
  ),
};

export const Empty: Story = {
  render: () => <ControlledRange initialValue={undefined} />,
};
