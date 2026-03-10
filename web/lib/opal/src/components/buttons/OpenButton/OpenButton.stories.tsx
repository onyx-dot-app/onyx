import type { Meta, StoryObj } from "@storybook/react";
import { OpenButton } from "@opal/components";
import { SvgSettings } from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof OpenButton> = {
  title: "opal/components/OpenButton",
  component: OpenButton,
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
type Story = StoryObj<typeof OpenButton>;

export const Default: Story = {
  args: {
    children: "Select option",
  },
};

export const WithIcon: Story = {
  args: {
    icon: SvgSettings,
    children: "Settings",
  },
};

export const Selected: Story = {
  args: {
    selected: true,
    children: "Selected",
  },
};

export const Open: Story = {
  args: {
    transient: true,
    children: "Open state",
  },
};

export const Disabled: Story = {
  args: {
    disabled: true,
    children: "Disabled",
  },
};

export const LightProminence: Story = {
  args: {
    prominence: "light",
    children: "Light prominence",
  },
};

export const HeavyProminence: Story = {
  args: {
    prominence: "heavy",
    children: "Heavy prominence",
  },
};

export const Sizes: Story = {
  render: () => (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      {(["lg", "md", "sm", "xs", "2xs"] as const).map((size) => (
        <OpenButton key={size} size={size}>
          {size}
        </OpenButton>
      ))}
    </div>
  ),
};
