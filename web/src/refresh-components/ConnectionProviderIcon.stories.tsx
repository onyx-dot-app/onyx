import type { Meta, StoryObj } from "@storybook/react";
import ConnectionProviderIcon from "./ConnectionProviderIcon";
import { SvgSettings, SvgStar } from "@opal/icons";

const meta: Meta<typeof ConnectionProviderIcon> = {
  title: "refresh-components/ConnectionProviderIcon",
  component: ConnectionProviderIcon,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
};

export default meta;
type Story = StoryObj<typeof ConnectionProviderIcon>;

export const WithSettingsIcon: Story = {
  args: {
    icon: <SvgSettings className="w-5 h-5 stroke-text-04" />,
  },
};

export const WithStarIcon: Story = {
  args: {
    icon: <SvgStar className="w-5 h-5 stroke-text-04" />,
  },
};

export const WithCustomEmoji: Story = {
  args: {
    icon: <span className="text-lg">📄</span>,
  },
};
