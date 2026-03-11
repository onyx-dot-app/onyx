import type { Meta, StoryObj } from "@storybook/react";
import InfoBlock from "./InfoBlock";
import { SvgAlertCircle, SvgCheckCircle, SvgSettings } from "@opal/icons";

const meta: Meta<typeof InfoBlock> = {
  title: "refresh-components/messages/InfoBlock",
  component: InfoBlock,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof InfoBlock>;

export const Default: Story = {
  args: {
    icon: SvgAlertCircle,
    title: "Important Notice",
    description: "This is a description providing additional context.",
  },
};

export const TitleOnly: Story = {
  args: {
    icon: SvgCheckCircle,
    title: "All systems operational",
  },
};

export const WithCustomIcon: Story = {
  args: {
    icon: SvgSettings,
    title: "Configuration Required",
    description: "Please update your settings before continuing.",
  },
};

export const LongContent: Story = {
  args: {
    icon: SvgAlertCircle,
    title:
      "This is a very long title that should get truncated when it exceeds the available width",
    description:
      "And this is a very long description that provides detailed context about the situation at hand and should also truncate gracefully.",
  },
};
