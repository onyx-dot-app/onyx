import type { Meta, StoryObj } from "@storybook/react";
import Button from "./Button";
import { SvgPlus, SvgArrowRight } from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof Button> = {
  title: "refresh-components/buttons/Button",
  component: Button,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <Story />
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof Button>;

export const Default: Story = {
  args: {
    children: "Button",
  },
};

export const Variants: Story = {
  render: () => (
    <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
      <Button main>Main</Button>
      <Button action>Action</Button>
      <Button danger>Danger</Button>
    </div>
  ),
};

export const Prominences: Story = {
  render: () => (
    <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
      <Button primary>Primary</Button>
      <Button secondary>Secondary</Button>
      <Button tertiary>Tertiary</Button>
    </div>
  ),
};

export const WithIcons: Story = {
  render: () => (
    <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
      <Button leftIcon={SvgPlus}>With Left Icon</Button>
      <Button rightIcon={SvgArrowRight}>With Right Icon</Button>
    </div>
  ),
};

export const Small: Story = {
  args: {
    size: "md",
    children: "Small Button",
  },
};

export const Disabled: Story = {
  args: {
    disabled: true,
    children: "Disabled",
  },
};

export const AsLink: Story = {
  args: {
    href: "https://example.com",
    children: "Link Button",
  },
};
