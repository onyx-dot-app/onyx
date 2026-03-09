import type { Meta, StoryObj } from "@storybook/react";
import SelectButton from "./SelectButton";
import { SvgFilter, SvgSettings } from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof SelectButton> = {
  title: "refresh-components/buttons/SelectButton",
  component: SelectButton,
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
type Story = StoryObj<typeof SelectButton>;

export const Default: Story = {
  args: {
    children: "Select Option",
  },
};

export const MainVariant: Story = {
  args: {
    main: true,
    children: "Main Select",
    leftIcon: SvgFilter,
  },
};

export const ActionVariant: Story = {
  args: {
    action: true,
    children: "Action Select",
    leftIcon: SvgSettings,
  },
};

export const Engaged: Story = {
  args: {
    action: true,
    engaged: true,
    children: "Engaged",
    leftIcon: SvgSettings,
  },
};

export const WithChevron: Story = {
  args: {
    main: true,
    children: "Dropdown",
    leftIcon: SvgFilter,
    rightChevronIcon: true,
  },
};

export const Transient: Story = {
  args: {
    main: true,
    transient: true,
    children: "Transient",
    leftIcon: SvgFilter,
    rightChevronIcon: true,
  },
};

export const Folded: Story = {
  args: {
    main: true,
    folded: true,
    children: "Folded Label",
    leftIcon: SvgFilter,
  },
};

export const FoldedAction: Story = {
  args: {
    action: true,
    folded: true,
    children: "Set as Default",
    rightIcon: SvgSettings,
  },
};

export const Disabled: Story = {
  args: {
    main: true,
    disabled: true,
    children: "Disabled",
    leftIcon: SvgFilter,
  },
};

export const ActionDisabled: Story = {
  args: {
    action: true,
    disabled: true,
    children: "Disabled Action",
    leftIcon: SvgSettings,
  },
};

export const AllStates: Story = {
  render: () => (
    <div
      style={{
        display: "flex",
        gap: 16,
        alignItems: "center",
        flexWrap: "wrap",
      }}
    >
      <SelectButton main leftIcon={SvgFilter}>
        Main
      </SelectButton>
      <SelectButton action leftIcon={SvgSettings}>
        Action
      </SelectButton>
      <SelectButton action engaged leftIcon={SvgSettings}>
        Engaged
      </SelectButton>
      <SelectButton main transient leftIcon={SvgFilter} rightChevronIcon>
        Transient
      </SelectButton>
      <SelectButton main disabled leftIcon={SvgFilter}>
        Disabled
      </SelectButton>
    </div>
  ),
};
