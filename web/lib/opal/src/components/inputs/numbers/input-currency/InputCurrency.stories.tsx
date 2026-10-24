import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { InputCurrency } from "@opal/components";

const meta: Meta<typeof InputCurrency> = {
  title: "opal/components/InputCurrency",
  component: InputCurrency,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof InputCurrency>;

export const Default: Story = {
  render: () => {
    const [amount, setAmount] = useState<number | null>(null);
    return (
      <div className="w-60">
        <InputCurrency value={amount} onChange={setAmount} />
      </div>
    );
  },
};

export const Filled: Story = {
  render: () => {
    const [amount, setAmount] = useState<number | null>(15);
    return (
      <div className="w-60">
        <InputCurrency value={amount} onChange={setAmount} />
      </div>
    );
  },
};

export const SubCentRate: Story = {
  render: () => {
    const [amount, setAmount] = useState<number | null>(0.075);
    return (
      <div className="w-60">
        <InputCurrency value={amount} onChange={setAmount} precision={6} />
      </div>
    );
  },
};

export const UnlimitedPrecision: Story = {
  render: () => {
    const [amount, setAmount] = useState<number | null>(0.01875);
    return (
      <div className="w-60">
        <InputCurrency
          value={amount}
          onChange={setAmount}
          precision="unlimited"
        />
      </div>
    );
  },
};

export const ZeroDecimalCurrency: Story = {
  render: () => {
    const [amount, setAmount] = useState<number | null>(1200);
    return (
      <div className="w-60">
        <InputCurrency value={amount} onChange={setAmount} currency="JPY" />
      </div>
    );
  },
};

export const Error: Story = {
  render: () => (
    <div className="w-60">
      <InputCurrency value={3} onChange={() => {}} error />
    </div>
  ),
};

export const Disabled: Story = {
  render: () => (
    <div className="w-60">
      <InputCurrency value={3} onChange={() => {}} disabled />
    </div>
  ),
};
