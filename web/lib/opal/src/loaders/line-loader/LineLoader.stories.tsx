import type { Meta, StoryObj } from "@storybook/react-vite";
import { LineLoader } from "@opal/loaders";

const meta: Meta<typeof LineLoader> = {
  title: "opal/loaders/LineLoader",
  component: LineLoader,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof LineLoader>;

export const OneLine: Story = {
  render: () => <LineLoader width="1/2" />,
};

export const Paragraph: Story = {
  render: () => <LineLoader lines={3} width="2/3" />,
};
