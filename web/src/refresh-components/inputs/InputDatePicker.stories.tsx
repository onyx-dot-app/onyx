import type { Meta, StoryObj } from "@storybook/react";
import React from "react";
import InputDatePicker from "./InputDatePicker";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof InputDatePicker> = {
  title: "refresh-components/inputs/InputDatePicker",
  component: InputDatePicker,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <div style={{ width: 320 }}>
          <Story />
        </div>
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof InputDatePicker>;

export const Default: Story = {
  render: function DefaultStory() {
    const [date, setDate] = React.useState<Date | null>(null);
    return <InputDatePicker selectedDate={date} setSelectedDate={setDate} />;
  },
};

export const WithSelectedDate: Story = {
  render: function SelectedDateStory() {
    const [date, setDate] = React.useState<Date | null>(new Date(2025, 0, 15));
    return <InputDatePicker selectedDate={date} setSelectedDate={setDate} />;
  },
};

export const CustomStartYear: Story = {
  render: function CustomStartYearStory() {
    const [date, setDate] = React.useState<Date | null>(null);
    return (
      <InputDatePicker
        selectedDate={date}
        setSelectedDate={setDate}
        startYear={2020}
      />
    );
  },
};

export const Disabled: Story = {
  render: () => (
    <InputDatePicker
      selectedDate={new Date()}
      setSelectedDate={() => {}}
      disabled
    />
  ),
};
