import React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { FilterButton } from "@opal/components";
import { Disabled as DisabledProvider } from "@opal/core";
import { SvgUser, SvgActions, SvgTag } from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof FilterButton> = {
  title: "opal/components/FilterButton",
  component: FilterButton,
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
type Story = StoryObj<typeof FilterButton>;

export const Empty: Story = {
  args: {
    icon: SvgUser,
    state: "empty",
    children: "Everyone",
  },
};

export const Selected: Story = {
  args: {
    icon: SvgUser,
    state: "selected",
    children: "By alice@example.com",
    onClear: () => console.log("clear"),
  },
};

export const Open: Story = {
  args: {
    icon: SvgActions,
    state: "empty",
    interaction: "hover",
    children: "All Actions",
  },
};

export const SelectedOpen: Story = {
  args: {
    icon: SvgActions,
    state: "selected",
    interaction: "hover",
    children: "2 selected",
    onClear: () => console.log("clear"),
  },
};

export const Disabled: Story = {
  args: {
    icon: SvgTag,
    state: "empty",
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

export const DisabledSelected: Story = {
  args: {
    icon: SvgTag,
    state: "selected",
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
      <FilterButton icon={SvgUser} state="empty">
        Everyone
      </FilterButton>
      <FilterButton
        icon={SvgUser}
        state="selected"
        onClear={() => console.log("clear")}
      >
        By alice@example.com
      </FilterButton>
    </div>
  ),
};

export const WithTooltip: Story = {
  args: {
    icon: SvgUser,
    state: "empty",
    children: "Everyone",
    tooltip: "Filter by creator",
    tooltipSide: "bottom",
  },
};
