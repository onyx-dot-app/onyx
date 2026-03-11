import type { Meta, StoryObj } from "@storybook/react";
import SimpleTabs from "./SimpleTabs";

const meta: Meta<typeof SimpleTabs> = {
  title: "refresh-components/SimpleTabs",
  component: SimpleTabs,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof SimpleTabs>;

export const Default: Story = {
  args: {
    tabs: {
      overview: {
        name: "Overview",
        content: <div style={{ padding: 16 }}>Overview content goes here.</div>,
      },
      settings: {
        name: "Settings",
        content: <div style={{ padding: 16 }}>Settings content goes here.</div>,
      },
      activity: {
        name: "Activity",
        content: <div style={{ padding: 16 }}>Activity content goes here.</div>,
      },
    },
    defaultValue: "overview",
  },
};

export const TwoTabs: Story = {
  args: {
    tabs: {
      users: {
        name: "Users",
        content: (
          <div style={{ padding: 16 }}>User management panel content.</div>
        ),
      },
      groups: {
        name: "Groups",
        content: (
          <div style={{ padding: 16 }}>Group management panel content.</div>
        ),
      },
    },
    defaultValue: "users",
  },
};

export const WithDisabledTab: Story = {
  args: {
    tabs: {
      active: {
        name: "Active",
        content: <div style={{ padding: 16 }}>This tab is active.</div>,
      },
      disabled: {
        name: "Disabled",
        content: <div style={{ padding: 16 }}>You should not see this.</div>,
        disabled: true,
      },
      another: {
        name: "Another",
        content: <div style={{ padding: 16 }}>Another tab content.</div>,
      },
    },
    defaultValue: "active",
  },
};
