import type { Meta, StoryObj } from "@storybook/react";
import React from "react";
import PasswordInputTypeIn from "./PasswordInputTypeIn";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof PasswordInputTypeIn> = {
  title: "refresh-components/inputs/PasswordInputTypeIn",
  component: PasswordInputTypeIn,
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
type Story = StoryObj<typeof PasswordInputTypeIn>;

export const Default: Story = {
  render: function DefaultStory() {
    const [value, setValue] = React.useState("");
    return (
      <PasswordInputTypeIn
        placeholder="Enter password..."
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
    );
  },
};

export const WithValue: Story = {
  render: function WithValueStory() {
    const [value, setValue] = React.useState("supersecret123");
    return (
      <PasswordInputTypeIn
        placeholder="Enter password..."
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
    );
  },
};

export const NonRevealable: Story = {
  render: function NonRevealableStory() {
    const [value, setValue] = React.useState("stored-secret-value");
    return (
      <PasswordInputTypeIn
        placeholder="Stored secret"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        isNonRevealable
      />
    );
  },
};

export const Disabled: Story = {
  render: () => (
    <PasswordInputTypeIn
      placeholder="Cannot edit"
      value="disabled-password"
      onChange={() => {}}
      disabled
    />
  ),
};

export const ErrorState: Story = {
  render: function ErrorStory() {
    const [value, setValue] = React.useState("bad");
    return (
      <PasswordInputTypeIn
        placeholder="Enter password..."
        value={value}
        onChange={(e) => setValue(e.target.value)}
        error
      />
    );
  },
};
