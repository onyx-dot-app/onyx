import type { Meta, StoryObj } from "@storybook/react";
import FilterButton from "./FilterButton";
import { SvgFilter, SvgCalendar, SvgUser } from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof FilterButton> = {
  title: "refresh-components/buttons/FilterButton",
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

export const Default: Story = {
  args: {
    leftIcon: SvgFilter,
    children: "Filter",
  },
};

export const Active: Story = {
  args: {
    leftIcon: SvgFilter,
    active: true,
    children: "Source: Google Drive",
    onClear: () => {},
  },
};

export const Transient: Story = {
  args: {
    leftIcon: SvgCalendar,
    transient: true,
    children: "Date Range",
  },
};

export const WithoutLabel: Story = {
  args: {
    leftIcon: SvgFilter,
  },
};

export const AllStates: Story = {
  render: () => (
    <div
      style={{
        display: "flex",
        gap: 12,
        alignItems: "center",
        flexWrap: "wrap",
      }}
    >
      <FilterButton leftIcon={SvgFilter}>Inactive</FilterButton>
      <FilterButton leftIcon={SvgFilter} transient>
        Transient
      </FilterButton>
      <FilterButton leftIcon={SvgCalendar} active onClear={() => {}}>
        Active Filter
      </FilterButton>
      <FilterButton leftIcon={SvgUser} active onClear={() => {}}>
        Author: John Doe
      </FilterButton>
    </div>
  ),
};
