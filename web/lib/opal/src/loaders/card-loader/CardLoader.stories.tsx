import type { Meta, StoryObj } from "@storybook/react-vite";
import { CardLoader } from "@opal/loaders";

const meta: Meta<typeof CardLoader> = {
  title: "opal/loaders/CardLoader",
  component: CardLoader,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof CardLoader>;

export const Default: Story = {
  render: () => <CardLoader />,
};

export const TwoDescriptionLines: Story = {
  render: () => <CardLoader descriptionLines={2} />,
};

// The card takes every Card prop.
export const CustomCard: Story = {
  render: () => (
    <div className="flex flex-col gap-3">
      <CardLoader border="dashed" rounding={3} color="transparent" />
      <CardLoader border="none" shadow="md" />
    </div>
  ),
};
