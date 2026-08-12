import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import {
  DateRangePicker,
  type DateRange,
} from "@/refresh-components/DateRangePicker";

const meta: Meta<typeof DateRangePicker> = {
  title: "components/DateRangePicker",
  component: DateRangePicker,
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
type Story = StoryObj<typeof DateRangePicker>;

function ControlledRange({ initialValue }: { initialValue: DateRange }) {
  const [value, setValue] = useState<DateRange>(initialValue);

  return <DateRangePicker value={value} onValueChange={setValue} />;
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
