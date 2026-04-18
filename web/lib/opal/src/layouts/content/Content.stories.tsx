import type { Meta, StoryObj } from "@storybook/react";
import { Content } from "@opal/layouts";
import { SvgSettings, SvgStar, SvgRefreshCw } from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta = {
  title: "Layouts/Content",
  component: Content,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <Story />
      </TooltipPrimitive.Provider>
    ),
  ],
} satisfies Meta<typeof Content>;

export default meta;

type Story = StoryObj<typeof meta>;

// ---------------------------------------------------------------------------
// XL stories (sizePreset: headline | section, variant: heading)
// ---------------------------------------------------------------------------

export const XlHeadline: Story = {
  args: {
    sizePreset: "headline",
    variant: "heading",
    title: "Welcome to Onyx",
    description: "Your enterprise search and AI assistant platform.",
  },
};

export const XlSection: Story = {
  args: {
    sizePreset: "section",
    variant: "heading",
    title: "Configuration",
  },
};

// ---------------------------------------------------------------------------
// LG stories (sizePreset: headline | section, variant: section)
// ---------------------------------------------------------------------------

export const LgHeadline: Story = {
  args: {
    sizePreset: "headline",
    variant: "section",
    title: "Connectors Overview",
  },
};

export const LgSection: Story = {
  args: {
    sizePreset: "section",
    variant: "section",
    title: "Data Sources",
  },
};

// ---------------------------------------------------------------------------
// MD stories (sizePreset: main-content | main-ui | secondary, variant: section)
// ---------------------------------------------------------------------------

export const MdMainContent: Story = {
  args: {
    sizePreset: "main-content",
    variant: "section",
    title: "General Settings",
    description: "Manage your workspace preferences.",
    icon: SvgSettings,
  },
};

export const MdWithTag: Story = {
  args: {
    sizePreset: "main-ui",
    variant: "section",
    title: "Knowledge Graph",
    tag: { title: "Beta", color: "blue" },
  },
};

export const MdMuted: Story = {
  args: {
    sizePreset: "secondary",
    variant: "section",
    title: "Advanced Options",
    description: "Fine-tune model behavior and parameters.",
  },
};

// ---------------------------------------------------------------------------
// SM stories (sizePreset: main-content | main-ui | secondary, variant: body)
// ---------------------------------------------------------------------------

export const SmBody: Story = {
  args: {
    sizePreset: "secondary",
    variant: "body",
    title: "Last synced 2 minutes ago",
  },
};

export const SmStacked: Story = {
  args: {
    sizePreset: "secondary",
    variant: "body",
    title: "Document count",
    orientation: "stacked",
  },
};

// ---------------------------------------------------------------------------
// Editable
// ---------------------------------------------------------------------------

export const Editable: Story = {
  args: {
    sizePreset: "main-ui",
    variant: "section",
    title: "Editable Title",
    editable: true,
  },
};

// ---------------------------------------------------------------------------
// MD — optional prop
// ---------------------------------------------------------------------------

export const MdWithOptional: Story = {
  args: {
    sizePreset: "main-content",
    variant: "section",
    title: "API Key",
    optional: true,
  },
};

// ---------------------------------------------------------------------------
// MD — auxIcon prop
// ---------------------------------------------------------------------------

export const MdWithAuxIcon: Story = {
  args: {
    sizePreset: "main-content",
    variant: "section",
    title: "Connection Status",
    auxIcon: "warning",
  },
};

// ---------------------------------------------------------------------------
// XL — moreIcon1 / moreIcon2 props
// ---------------------------------------------------------------------------

export const XlWithMoreIcons: Story = {
  args: {
    sizePreset: "headline",
    variant: "heading",
    title: "Dashboard",
    moreIcon1: SvgStar,
    moreIcon2: SvgRefreshCw,
  },
};

// ---------------------------------------------------------------------------
// SM — prominence: muted
// ---------------------------------------------------------------------------

export const SmMuted: Story = {
  args: {
    sizePreset: "secondary",
    variant: "body",
    title: "Updated 5 min ago",
    prominence: "muted",
  },
};

// ---------------------------------------------------------------------------
// width: full
// ---------------------------------------------------------------------------

export const WidthFull: Story = {
  args: {
    sizePreset: "main-content",
    variant: "section",
    title: "Full Width Content",
    width: "full",
  },
  decorators: [
    (Story) => (
      <div style={{ width: 600, border: "1px dashed gray" }}>
        <Story />
      </div>
    ),
  ],
};
