import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { InputTime, type TimeValue } from "@opal/components";

const meta: Meta<typeof InputTime> = {
  title: "opal/components/InputTime",
  component: InputTime,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof InputTime>;

export const Default: Story = {
  render: () => {
    const [time, setTime] = useState<TimeValue | null>(null);
    return (
      <div className="w-60">
        <InputTime value={time} onChange={setTime} />
      </div>
    );
  },
};

export const Filled: Story = {
  render: () => {
    const [time, setTime] = useState<TimeValue | null>({
      hours: 18,
      minutes: 40,
      seconds: 59,
    });
    return (
      <div className="w-60">
        <InputTime value={time} onChange={setTime} clearable />
      </div>
    );
  },
};

export const WithoutSeconds: Story = {
  render: () => {
    const [time, setTime] = useState<TimeValue | null>({
      hours: 9,
      minutes: 30,
      seconds: 0,
    });
    return (
      <div className="w-60">
        <InputTime value={time} onChange={setTime} showSeconds={false} />
      </div>
    );
  },
};

export const Error: Story = {
  render: () => {
    const [time, setTime] = useState<TimeValue | null>(null);
    return (
      <div className="w-60">
        <InputTime value={time} onChange={setTime} error />
      </div>
    );
  },
};

export const Disabled: Story = {
  render: () => (
    <div className="w-60">
      <InputTime
        value={{ hours: 18, minutes: 40, seconds: 59 }}
        onChange={() => undefined}
        disabled
      />
    </div>
  ),
};
