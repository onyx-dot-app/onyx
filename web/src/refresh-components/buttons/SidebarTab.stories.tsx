import type { Meta, StoryObj } from "@storybook/react";
import SidebarTab from "./SidebarTab";
import {
  SvgDashboard,
  SvgSettings,
  SvgUser,
  SvgFolder,
  SvgSearch,
} from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof SidebarTab> = {
  title: "refresh-components/buttons/SidebarTab",
  component: SidebarTab,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <div
          style={{
            width: 260,
            background: "var(--background-neutral-01)",
            padding: 8,
            borderRadius: 12,
          }}
        >
          <Story />
        </div>
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof SidebarTab>;

export const Default: Story = {
  args: {
    icon: SvgDashboard,
    children: "Home",
  },
};

export const Selected: Story = {
  args: {
    icon: SvgDashboard,
    children: "Home",
    selected: true,
  },
};

export const Lowlight: Story = {
  args: {
    icon: SvgFolder,
    children: "Archived",
    lowlight: true,
  },
};

export const Nested: Story = {
  args: {
    children: "Sub-item",
    nested: true,
  },
};

export const Folded: Story = {
  args: {
    icon: SvgDashboard,
    children: "Home",
    folded: true,
  },
};

export const SidebarNavigation: Story = {
  render: () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <SidebarTab icon={SvgDashboard} selected>
        Home
      </SidebarTab>
      <SidebarTab icon={SvgSearch}>Search</SidebarTab>
      <SidebarTab icon={SvgFolder}>Documents</SidebarTab>
      <SidebarTab icon={SvgUser}>Profile</SidebarTab>
      <SidebarTab icon={SvgSettings}>Settings</SidebarTab>
      <SidebarTab nested>Sub-item A</SidebarTab>
      <SidebarTab nested>Sub-item B</SidebarTab>
    </div>
  ),
};
