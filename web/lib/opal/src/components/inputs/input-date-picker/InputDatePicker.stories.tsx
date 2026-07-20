import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { InputDatePicker } from "@opal/components";

const meta: Meta<typeof InputDatePicker> = {
  title: "opal/components/InputDatePicker",
  component: InputDatePicker,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof InputDatePicker>;

export const Default: Story = {
  render: () => {
    const [date, setDate] = useState<Date | null>(null);
    return (
      <div className="w-60">
        <InputDatePicker value={date} onChange={setDate} />
      </div>
    );
  },
};

export const Filled: Story = {
  render: () => {
    const [date, setDate] = useState<Date | null>(new Date(2025, 11, 16));
    return (
      <div className="w-60">
        <InputDatePicker value={date} onChange={setDate} clearable />
      </div>
    );
  },
};

export const PastOnly: Story = {
  render: () => {
    const [date, setDate] = useState<Date | null>(null);
    return (
      <div className="w-60">
        <InputDatePicker value={date} onChange={setDate} maxDate={new Date()} />
      </div>
    );
  },
};

export const BoundedRange: Story = {
  render: () => {
    const [date, setDate] = useState<Date | null>(null);
    const today = new Date();
    const weekAgo = new Date(today);
    weekAgo.setDate(today.getDate() - 7);
    const weekAhead = new Date(today);
    weekAhead.setDate(today.getDate() + 7);
    return (
      <div className="w-60">
        <InputDatePicker
          value={date}
          onChange={setDate}
          minDate={weekAgo}
          maxDate={weekAhead}
        />
      </div>
    );
  },
};

export const Error: Story = {
  render: () => {
    const [date, setDate] = useState<Date | null>(null);
    return (
      <div className="w-60">
        <InputDatePicker value={date} onChange={setDate} error />
      </div>
    );
  },
};

export const Disabled: Story = {
  render: () => (
    <div className="w-60">
      <InputDatePicker
        value={new Date(2025, 11, 16)}
        onChange={() => undefined}
        disabled
      />
    </div>
  ),
};
