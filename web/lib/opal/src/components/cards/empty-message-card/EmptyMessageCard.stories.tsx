import type { Meta, StoryObj } from "@storybook/react";
import { EmptyMessageCard } from "@opal/components";
import { SvgActions, SvgServer, SvgSparkle, SvgUsers } from "@opal/icons";

const PADDING_VARIANTS = ["fit", "2xs", "xs", "sm", "md", "lg"] as const;

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

export const MainUi: Story = {
  args: {
    sizePreset: "main-ui",
    title: "No Actions Found",
    icon: SvgActions,
    description: "Provide OpenAPI schema to preview actions here.",
  },
};

export const MainUiNoDescription: Story = {
  args: {
    sizePreset: "main-ui",
    title: "No Knowledge",
  },
};

export const PaddingVariants: Story = {
  render: () => (
    <div className="flex flex-col gap-4 w-96">
      {PADDING_VARIANTS.map((padding) => (
        <EmptyMessageCard
          key={padding}
          padding={padding}
          title={`padding: ${padding}`}
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
      <EmptyMessageCard
        sizePreset="main-ui"
        icon={SvgServer}
        title="No Discord servers configured yet"
        description="Create a server configuration to get started."
      />
    </div>
  ),
};
