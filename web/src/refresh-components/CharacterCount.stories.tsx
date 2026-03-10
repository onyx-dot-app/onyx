import type { Meta, StoryObj } from "@storybook/react";
import CharacterCount from "./CharacterCount";

const meta: Meta<typeof CharacterCount> = {
  title: "refresh-components/CharacterCount",
  component: CharacterCount,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
};

export default meta;
type Story = StoryObj<typeof CharacterCount>;

export const UnderLimit: Story = {
  args: {
    value: "Hello world",
    limit: 100,
  },
};

export const NearLimit: Story = {
  args: {
    value: "A".repeat(95),
    limit: 100,
  },
};

export const AtLimit: Story = {
  args: {
    value: "A".repeat(100),
    limit: 100,
  },
};

export const Empty: Story = {
  args: {
    value: "",
    limit: 256,
  },
};
