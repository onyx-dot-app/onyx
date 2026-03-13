import type { Meta, StoryObj } from "@storybook/react";
import { NameCard } from "./components";
import { SvgUser, SvgSettings } from "@opal/icons";
import { Button } from "@opal/components";

const meta: Meta<typeof NameCard> = {
  title: "opal/cards/NameCard",
  component: NameCard,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof NameCard>;

export const Default: Story = {
  args: {
    title: "Anthropic",
    icon: SvgUser,
  },
};

export const WithDescription: Story = {
  args: {
    title: "GPT-4o",
    description: "OpenAI's flagship model",
    icon: SvgSettings,
  },
};

export const WithRightChildren: Story = {
  args: {
    title: "Claude Sonnet",
    description: "Fast and capable",
    icon: SvgUser,
    rightChildren: <Button prominence="tertiary">Edit</Button>,
  },
};

export const WithCustomIcon: Story = {
  args: {
    title: "Custom Provider",
    description: "A provider with a custom icon element",
    customIcon: (
      <div className="h-4 w-4 rounded-full bg-theme-primary-05" />
    ),
  },
};
