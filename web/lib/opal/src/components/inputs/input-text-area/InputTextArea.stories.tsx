import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { InputTextArea } from "@opal/components";

const meta: Meta<typeof InputTextArea> = {
  title: "opal/components/InputTextArea",
  component: InputTextArea,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof InputTextArea>;

function ControlledInputTextArea(
  props: Partial<React.ComponentProps<typeof InputTextArea>>
) {
  const [value, setValue] = useState("");
  return (
    <div className="w-96">
      <InputTextArea
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="Enter a description…"
        {...props}
      />
    </div>
  );
}

export const Default: Story = {
  render: () => <ControlledInputTextArea />,
};

export const AutoResize: Story = {
  render: () => <ControlledInputTextArea autoResize rows={2} maxRows={6} />,
};

export const Error: Story = {
  render: () => <ControlledInputTextArea variant="error" />,
};

export const Disabled: Story = {
  render: () => (
    <div className="w-96">
      <InputTextArea
        variant="disabled"
        value="Cannot edit"
        onChange={() => {}}
      />
    </div>
  ),
};

export const ReadOnly: Story = {
  render: () => (
    <div className="w-96">
      <InputTextArea
        variant="readOnly"
        value="Read-only value"
        onChange={() => {}}
      />
    </div>
  ),
};

export const Internal: Story = {
  render: () => <ControlledInputTextArea variant="internal" />,
};
