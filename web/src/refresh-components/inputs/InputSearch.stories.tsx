import type { Meta, StoryObj } from "@storybook/react";
import React from "react";
import InputSearch from "./InputSearch";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof InputSearch> = {
  title: "refresh-components/inputs/InputSearch",
  component: InputSearch,
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
type Story = StoryObj<typeof InputSearch>;

export const Default: Story = {
  render: function DefaultStory() {
    const [value, setValue] = React.useState("");
    return (
      <InputSearch
        placeholder="Search..."
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
    );
  },
};

export const WithValue: Story = {
  render: function WithValueStory() {
    const [value, setValue] = React.useState("Search Value");
    return (
      <InputSearch
        placeholder="Search..."
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
    );
  },
};

export const Disabled: Story = {
  render: function DisabledStory() {
    return (
      <InputSearch
        placeholder="Search..."
        value=""
        onChange={() => {}}
        disabled
      />
    );
  },
};
