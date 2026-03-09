import type { Meta, StoryObj } from "@storybook/react";
import Tabs from "./Tabs";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { SvgSettings, SvgStar, SvgRefreshCw } from "@opal/icons";

const meta: Meta<typeof Tabs> = {
  title: "refresh-components/Tabs",
  component: Tabs,
  tags: ["autodocs"],
  parameters: {
    layout: "padded",
  },
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <Story />
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof Tabs>;

// ---------------------------------------------------------------------------
// Contained variant (default)
// ---------------------------------------------------------------------------

export const Contained: Story = {
  render: () => (
    <Tabs defaultValue="overview">
      <Tabs.List variant="contained">
        <Tabs.Trigger value="overview">Overview</Tabs.Trigger>
        <Tabs.Trigger value="details">Details</Tabs.Trigger>
        <Tabs.Trigger value="settings">Settings</Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="overview">Overview tab content</Tabs.Content>
      <Tabs.Content value="details">Details tab content</Tabs.Content>
      <Tabs.Content value="settings">Settings tab content</Tabs.Content>
    </Tabs>
  ),
};

// ---------------------------------------------------------------------------
// Pill variant
// ---------------------------------------------------------------------------

export const Pill: Story = {
  render: () => (
    <Tabs defaultValue="all">
      <Tabs.List variant="pill">
        <Tabs.Trigger value="all">All</Tabs.Trigger>
        <Tabs.Trigger value="active">Active</Tabs.Trigger>
        <Tabs.Trigger value="archived">Archived</Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="all">All items</Tabs.Content>
      <Tabs.Content value="active">Active items</Tabs.Content>
      <Tabs.Content value="archived">Archived items</Tabs.Content>
    </Tabs>
  ),
};

// ---------------------------------------------------------------------------
// With icons
// ---------------------------------------------------------------------------

export const WithIcons: Story = {
  render: () => (
    <Tabs defaultValue="general">
      <Tabs.List variant="contained">
        <Tabs.Trigger value="general" icon={SvgSettings}>
          General
        </Tabs.Trigger>
        <Tabs.Trigger value="favorites" icon={SvgStar}>
          Favorites
        </Tabs.Trigger>
        <Tabs.Trigger value="sync" icon={SvgRefreshCw}>
          Sync
        </Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="general">General settings</Tabs.Content>
      <Tabs.Content value="favorites">Your favorites</Tabs.Content>
      <Tabs.Content value="sync">Sync configuration</Tabs.Content>
    </Tabs>
  ),
};

// ---------------------------------------------------------------------------
// Pill with right content
// ---------------------------------------------------------------------------

export const PillWithRightContent: Story = {
  render: () => (
    <Tabs defaultValue="users">
      <Tabs.List
        variant="pill"
        rightContent={
          <button className="px-3 py-1 text-sm bg-background-tint-03 rounded-08">
            Add New
          </button>
        }
      >
        <Tabs.Trigger value="users">Users</Tabs.Trigger>
        <Tabs.Trigger value="groups">Groups</Tabs.Trigger>
        <Tabs.Trigger value="roles">Roles</Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="users">Users list</Tabs.Content>
      <Tabs.Content value="groups">Groups list</Tabs.Content>
      <Tabs.Content value="roles">Roles list</Tabs.Content>
    </Tabs>
  ),
};

// ---------------------------------------------------------------------------
// With disabled and tooltip
// ---------------------------------------------------------------------------

export const WithDisabledTab: Story = {
  render: () => (
    <Tabs defaultValue="active">
      <Tabs.List variant="contained">
        <Tabs.Trigger value="active">Active</Tabs.Trigger>
        <Tabs.Trigger value="pending" disabled tooltip="Coming soon">
          Pending
        </Tabs.Trigger>
        <Tabs.Trigger value="completed">Completed</Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="active">Active tasks</Tabs.Content>
      <Tabs.Content value="completed">Completed tasks</Tabs.Content>
    </Tabs>
  ),
};

// ---------------------------------------------------------------------------
// Loading state
// ---------------------------------------------------------------------------

export const LoadingTab: Story = {
  render: () => (
    <Tabs defaultValue="data">
      <Tabs.List variant="pill">
        <Tabs.Trigger value="data" isLoading>
          Loading Data
        </Tabs.Trigger>
        <Tabs.Trigger value="ready">Ready</Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="data">Data is loading...</Tabs.Content>
      <Tabs.Content value="ready">Ready content</Tabs.Content>
    </Tabs>
  ),
};
