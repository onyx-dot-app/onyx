import type { Meta, StoryObj } from "@storybook/react";
import { BodyLayout } from "./BodyLayout";
import { SvgSettings, SvgStar, SvgRefreshCw } from "@opal/icons";

const meta = {
  title: "Layouts/BodyLayout",
  component: BodyLayout,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
} satisfies Meta<typeof BodyLayout>;

export default meta;

type Story = StoryObj<typeof meta>;

// ---------------------------------------------------------------------------
// Size presets
// ---------------------------------------------------------------------------

export const MainContent: Story = {
  args: {
    sizePreset: "main-content",
    title: "Last synced 2 minutes ago",
  },
};

export const MainUi: Story = {
  args: {
    sizePreset: "main-ui",
    title: "Document count: 1,234",
  },
};

export const Secondary: Story = {
  args: {
    sizePreset: "secondary",
    title: "Updated 5 min ago",
  },
};

// ---------------------------------------------------------------------------
// With icon
// ---------------------------------------------------------------------------

export const WithIcon: Story = {
  args: {
    sizePreset: "main-ui",
    title: "Settings",
    icon: SvgSettings,
  },
};

// ---------------------------------------------------------------------------
// Orientations
// ---------------------------------------------------------------------------

export const Vertical: Story = {
  args: {
    sizePreset: "main-ui",
    title: "Stacked layout",
    icon: SvgStar,
    orientation: "vertical",
  },
};

export const Reverse: Story = {
  args: {
    sizePreset: "main-ui",
    title: "Reverse layout",
    icon: SvgRefreshCw,
    orientation: "reverse",
  },
};

// ---------------------------------------------------------------------------
// Prominence
// ---------------------------------------------------------------------------

export const Muted: Story = {
  args: {
    sizePreset: "main-ui",
    title: "Muted body text",
    prominence: "muted",
  },
};
