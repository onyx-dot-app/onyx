import type { Meta, StoryObj } from "@storybook/react";
import TextSeparator from "./TextSeparator";

const meta: Meta<typeof TextSeparator> = {
  title: "refresh-components/TextSeparator",
  component: TextSeparator,
  tags: ["autodocs"],
  parameters: {
    layout: "padded",
  },
};

export default meta;
type Story = StoryObj<typeof TextSeparator>;

export const TextOnly: Story = {
  args: {
    text: "Older messages",
  },
};

export const WithCount: Story = {
  args: {
    text: "results",
    count: 42,
  },
};

export const InContext: Story = {
  render: () => (
    <div className="flex flex-col gap-2" style={{ width: 400 }}>
      <div className="p-2 bg-background-tint-01 rounded-08">Message 1</div>
      <div className="p-2 bg-background-tint-01 rounded-08">Message 2</div>
      <TextSeparator text="older messages" count={15} />
      <div className="p-2 bg-background-tint-01 rounded-08">Message 3</div>
      <div className="p-2 bg-background-tint-01 rounded-08">Message 4</div>
    </div>
  ),
};
