import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { InputPasswordTypeIn } from "@opal/components";

const meta: Meta<typeof InputPasswordTypeIn> = {
  title: "opal/components/InputPasswordTypeIn",
  component: InputPasswordTypeIn,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof InputPasswordTypeIn>;

function Harness(props: {
  initialValue?: string;
  isNonRevealable?: boolean;
  placeholder?: string;
  error?: boolean;
  disabled?: boolean;
  mask?: "asterisk" | "native";
}) {
  const { initialValue = "", ...rest } = props;
  const [value, setValue] = useState(initialValue);
  return (
    <div className="w-72">
      <InputPasswordTypeIn
        value={value}
        onChange={(e) => setValue(e.target.value)}
        {...rest}
      />
    </div>
  );
}

export const Empty: Story = {
  render: () => <Harness placeholder="Your long-term API key" />,
};

export const Filled: Story = {
  render: () => <Harness initialValue="hunter2-hunter2" />,
};

export const NativeMask: Story = {
  render: () => <Harness initialValue="hunter2-hunter2" mask="native" />,
};

export const NonRevealable: Story = {
  render: () => <Harness initialValue="hunter2-hunter2" isNonRevealable />,
};

export const AutoDetectedStoredSecret: Story = {
  render: () => <Harness initialValue="••••••••" />,
};

export const Error: Story = {
  render: () => <Harness initialValue="wrong-secret" error />,
};

export const Disabled: Story = {
  render: () => <Harness initialValue="hunter2-hunter2" disabled />,
};
