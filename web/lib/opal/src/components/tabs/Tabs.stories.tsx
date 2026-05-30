import type { Meta, StoryObj } from "@storybook/react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { SvgSettings, SvgStar, SvgRefreshCw, SvgUser } from "@opal/icons";
import { Button } from "@opal/components/buttons/button/components";
import { Tabs } from "./components";

const withTooltipProvider = (Story: React.ComponentType) => (
  <TooltipPrimitive.Provider>
    <Story />
  </TooltipPrimitive.Provider>
);

const meta = {
  title: "Components/Tabs",
  component: Tabs,
  decorators: [withTooltipProvider],
  parameters: { layout: "padded" },
} satisfies Meta<typeof Tabs>;

export default meta;
type Story = StoryObj<typeof meta>;

/* ── Contained (default) ────────────────────────────────────────────────────── */

export const Contained: Story = {
  render: () => (
    <Tabs defaultValue="overview">
      <Tabs.List>
        <Tabs.Trigger value="overview">Overview</Tabs.Trigger>
        <Tabs.Trigger value="details">Details</Tabs.Trigger>
        <Tabs.Trigger value="history">History</Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="overview">Overview content</Tabs.Content>
      <Tabs.Content value="details">Details content</Tabs.Content>
      <Tabs.Content value="history">History content</Tabs.Content>
    </Tabs>
  ),
};

/* ── Pill ───────────────────────────────────────────────────────────────────── */

export const Pill: Story = {
  render: () => (
    <Tabs defaultValue="all" variant="pill">
      <Tabs.List>
        <Tabs.Trigger value="all">All</Tabs.Trigger>
        <Tabs.Trigger value="active">Active</Tabs.Trigger>
        <Tabs.Trigger value="paused">Paused</Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="all">All items</Tabs.Content>
      <Tabs.Content value="active">Active items</Tabs.Content>
      <Tabs.Content value="paused">Paused items</Tabs.Content>
    </Tabs>
  ),
};

/* ── Underline ──────────────────────────────────────────────────────────────── */

export const Underline: Story = {
  render: () => (
    <Tabs defaultValue="cloud" variant="underline">
      <Tabs.List>
        <Tabs.Trigger value="cloud">Cloud-based</Tabs.Trigger>
        <Tabs.Trigger value="self">Self-hosted</Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="cloud">Cloud model options</Tabs.Content>
      <Tabs.Content value="self">Self-hosted model options</Tabs.Content>
    </Tabs>
  ),
};

/* ── With icons ─────────────────────────────────────────────────────────────── */

export const WithIcons: Story = {
  render: () => (
    <Tabs defaultValue="profile">
      <Tabs.List>
        <Tabs.Trigger value="profile" icon={SvgUser}>
          Profile
        </Tabs.Trigger>
        <Tabs.Trigger value="settings" icon={SvgSettings}>
          Settings
        </Tabs.Trigger>
        <Tabs.Trigger value="favorites" icon={SvgStar}>
          Favorites
        </Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="profile">Profile content</Tabs.Content>
      <Tabs.Content value="settings">Settings content</Tabs.Content>
      <Tabs.Content value="favorites">Favorites content</Tabs.Content>
    </Tabs>
  ),
};

/* ── Tooltips and disabled ──────────────────────────────────────────────────── */

export const TooltipsAndDisabled: Story = {
  render: () => (
    <Tabs defaultValue="active">
      <Tabs.List>
        <Tabs.Trigger value="active" tooltip="Currently active items">
          Active
        </Tabs.Trigger>
        <Tabs.Trigger
          value="premium"
          disabled
          tooltip="Upgrade to access premium features"
        >
          Premium
        </Tabs.Trigger>
        <Tabs.Trigger value="archived" tooltip="Previously completed items">
          Archived
        </Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="active">Active content</Tabs.Content>
      <Tabs.Content value="archived">Archived content</Tabs.Content>
    </Tabs>
  ),
};

/* ── Right content ──────────────────────────────────────────────────────────── */

export const RightContent: Story = {
  render: () => (
    <Tabs defaultValue="all" variant="pill">
      <Tabs.List
        rightChildren={
          <Button size="sm" prominence="secondary" icon={SvgRefreshCw}>
            Refresh
          </Button>
        }
      >
        <Tabs.Trigger value="all">All</Tabs.Trigger>
        <Tabs.Trigger value="mine">Mine</Tabs.Trigger>
        <Tabs.Trigger value="shared">Shared</Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="all">All items</Tabs.Content>
      <Tabs.Content value="mine">My items</Tabs.Content>
      <Tabs.Content value="shared">Shared items</Tabs.Content>
    </Tabs>
  ),
};

/* ── Loading trigger ────────────────────────────────────────────────────────── */

export const Loading: Story = {
  render: () => (
    <Tabs defaultValue="syncing">
      <Tabs.List>
        <Tabs.Trigger value="ready">Ready</Tabs.Trigger>
        <Tabs.Trigger value="syncing" isLoading>
          Syncing
        </Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="ready">Ready content</Tabs.Content>
      <Tabs.Content value="syncing">Syncing…</Tabs.Content>
    </Tabs>
  ),
};

/* ── Scroll arrows ──────────────────────────────────────────────────────────── */

export const ScrollArrows: Story = {
  render: () => (
    <div style={{ width: 320 }}>
      <Tabs defaultValue="tab1" variant="pill">
        <Tabs.List enableScrollArrows>
          {Array.from({ length: 10 }, (_, i) => (
            <Tabs.Trigger key={i + 1} value={`tab${i + 1}`}>
              {`Tab ${i + 1}`}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        {Array.from({ length: 10 }, (_, i) => (
          <Tabs.Content key={i + 1} value={`tab${i + 1}`}>
            {`Content for Tab ${i + 1}`}
          </Tabs.Content>
        ))}
      </Tabs>
    </div>
  ),
};

/* ── Content padding ────────────────────────────────────────────────────────── */

export const ContentPadding: Story = {
  render: () => (
    <Tabs defaultValue="padded">
      <Tabs.List>
        <Tabs.Trigger value="padded">Padded</Tabs.Trigger>
        <Tabs.Trigger value="flush">Flush</Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="padded" padding={1}>
        <div className="border border-border-02 rounded-08 p-4">
          Inner content with 1rem padding
        </div>
      </Tabs.Content>
      <Tabs.Content value="flush">
        <div className="border border-border-02 rounded-08 p-4">
          Flush content (no extra padding)
        </div>
      </Tabs.Content>
    </Tabs>
  ),
};
