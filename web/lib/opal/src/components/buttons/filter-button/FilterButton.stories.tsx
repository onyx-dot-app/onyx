import type { Meta, StoryObj } from "@storybook/react";
import { FilterButton } from "@opal/components";
import { Disabled as DisabledProvider } from "@opal/core";
import { SvgUser, SvgActions, SvgTag } from "@opal/icons";

const meta: Meta<typeof FilterButton> = {
  title: "opal/components/FilterButton",
  component: FilterButton,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof FilterButton>;

export const Empty: Story = {
  args: {
    icon: SvgUser,
    children: "Everyone",
  },
};

export const Active: Story = {
  args: {
    icon: SvgUser,
    active: true,
    children: "By alice@example.com",
    onClear: () => console.log("clear"),
  },
};

export const Open: Story = {
  args: {
    icon: SvgActions,
    interaction: "hover",
    children: "All Actions",
  },
};

export const ActiveOpen: Story = {
  args: {
    icon: SvgActions,
    active: true,
    interaction: "hover",
    children: "2 selected",
    onClear: () => console.log("clear"),
  },
};

export const Disabled: Story = {
  args: {
    icon: SvgTag,
    children: "All Tags",
  },
  decorators: [
    (Story) => (
      <DisabledProvider disabled>
        <Story />
      </DisabledProvider>
    ),
  ],
};

export const DisabledActive: Story = {
  args: {
    icon: SvgTag,
    active: true,
    children: "2 tags",
    onClear: () => console.log("clear"),
  },
  decorators: [
    (Story) => (
      <DisabledProvider disabled>
        <Story />
      </DisabledProvider>
    ),
  ],
};

export const StateComparison: Story = {
  render: () => (
    <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
      <FilterButton icon={SvgUser} onClear={() => undefined}>
        Everyone
      </FilterButton>
      <FilterButton icon={SvgUser} active onClear={() => console.log("clear")}>
        By alice@example.com
      </FilterButton>
    </div>
  ),
};

export const WithTooltip: Story = {
  args: {
    icon: SvgUser,
    children: "Everyone",
    tooltip: "Filter by creator",
    tooltipSide: "bottom",
  },
};
