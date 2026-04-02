import React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { SidebarTab } from "@opal/components/buttons/sidebar-tab/components";
import { SvgSettings, SvgUsers, SvgLock, SvgArrowUpCircle } from "@opal/icons";
import { Button } from "@opal/components";
import { SvgTrash } from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof SidebarTab> = {
  title: "opal/components/SidebarTab",
  component: SidebarTab,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <div style={{ width: 260, background: "var(--background-neutral-01)" }}>
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
    icon: SvgSettings,
    children: "Settings",
  },
};

export const Selected: Story = {
  args: {
    icon: SvgSettings,
    children: "Settings",
    state: "selected",
  },
};

export const Light: Story = {
  args: {
    icon: SvgSettings,
    children: "Settings",
    variant: "sidebar-light",
  },
};

export const Disabled: Story = {
  args: {
    icon: SvgLock,
    children: "Enterprise Only",
    disabled: true,
  },
};

export const WithRightChildren: Story = {
  args: {
    icon: SvgUsers,
    children: "Users",
    rightChildren: (
      <Button
        icon={SvgTrash}
        size="xs"
        prominence="tertiary"
        variant="danger"
      />
    ),
  },
};

export const SidebarExample: Story = {
  render: () => (
    <div className="flex flex-col">
      <SidebarTab icon={SvgSettings} state="selected">
        LLM Models
      </SidebarTab>
      <SidebarTab icon={SvgSettings}>Web Search</SidebarTab>
      <SidebarTab icon={SvgUsers}>Users</SidebarTab>
      <SidebarTab icon={SvgLock} disabled>
        Groups
      </SidebarTab>
      <SidebarTab icon={SvgLock} disabled>
        SCIM
      </SidebarTab>
      <SidebarTab icon={SvgArrowUpCircle}>Upgrade Plan</SidebarTab>
    </div>
  ),
};
