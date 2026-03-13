import type { Meta, StoryObj } from "@storybook/react";
import SquareButton from "./SquareButton";
import { SvgPlus, SvgSettings, SvgSearch, SvgX } from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof SquareButton> = {
  title: "refresh-components/buttons/SquareButton",
  component: SquareButton,
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
type Story = StoryObj<typeof SquareButton>;

export const Default: Story = {
  args: {
    icon: SvgPlus,
  },
};

export const Transient: Story = {
  args: {
    icon: SvgSettings,
    transient: true,
  },
};

export const Disabled: Story = {
  args: {
    icon: SvgPlus,
    disabled: true,
  },
};

export const AllVariants: Story = {
  render: () => (
    <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
      <SquareButton icon={SvgPlus} />
      <SquareButton icon={SvgSettings} transient />
      <SquareButton icon={SvgSearch} />
      <SquareButton icon={SvgX} />
      <SquareButton icon={SvgPlus} disabled />
    </div>
  ),
};
