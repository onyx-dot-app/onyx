import type { Meta, StoryObj } from "@storybook/react";
import { EmptyMessageCard } from "@opal/components";
import { SvgSparkle, SvgUsers } from "@opal/icons";

const SIZE_VARIANTS = ["lg", "md", "sm", "xs", "2xs", "fit"] as const;

const meta: Meta<typeof EmptyMessageCard> = {
  title: "opal/components/EmptyMessageCard",
  component: EmptyMessageCard,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof EmptyMessageCard>;

export const Default: Story = {
  args: {
    title: "No items available.",
  },
};

export const WithCustomIcon: Story = {
  args: {
    icon: SvgSparkle,
    title: "No agents selected.",
  },
};

export const SizeVariants: Story = {
  render: () => (
    <div className="flex flex-col gap-4 w-96">
      {SIZE_VARIANTS.map((size) => (
        <EmptyMessageCard
          key={size}
          sizeVariant={size}
          title={`sizeVariant: ${size}`}
        />
      ))}
    </div>
  ),
};

export const Multiple: Story = {
  render: () => (
    <div className="flex flex-col gap-4 w-96">
      <EmptyMessageCard title="No models available." />
      <EmptyMessageCard icon={SvgSparkle} title="No agents selected." />
      <EmptyMessageCard icon={SvgUsers} title="No groups added." />
    </div>
  ),
};
