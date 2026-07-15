import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react";
import type { DateRange } from "react-day-picker";
import { Calendar } from "@opal/components";

const meta: Meta<typeof Calendar> = {
  title: "opal/components/Calendar",
  component: Calendar,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Calendar>;

export const Single: Story = {
  render: () => {
    const [selected, setSelected] = useState<Date | undefined>(
      new Date(2025, 11, 16)
    );
    return (
      <Calendar
        mode="single"
        selected={selected}
        onSelect={setSelected}
        defaultMonth={new Date(2025, 11)}
      />
    );
  },
};

export const Range: Story = {
  render: () => {
    const [range, setRange] = useState<DateRange | undefined>({
      from: new Date(2025, 11, 16),
      to: new Date(2025, 11, 24),
    });
    return (
      <Calendar
        mode="range"
        selected={range}
        onSelect={setRange}
        defaultMonth={new Date(2025, 11)}
      />
    );
  },
};

export const DisabledFutureDates: Story = {
  render: () => {
    const [selected, setSelected] = useState<Date | undefined>(undefined);
    const today = new Date();
    return (
      <Calendar
        mode="single"
        selected={selected}
        onSelect={setSelected}
        disabled={[{ after: today }]}
        endMonth={today}
      />
    );
  },
};

export const TwoMonths: Story = {
  render: () => (
    <Calendar
      mode="single"
      numberOfMonths={2}
      defaultMonth={new Date(2025, 11)}
    />
  ),
};
