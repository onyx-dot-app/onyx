import type { Meta, StoryObj } from "@storybook/react";
import CustomAgentAvatar from "./CustomAgentAvatar";

const meta: Meta<typeof CustomAgentAvatar> = {
  title: "refresh-components/Avatars/CustomAgentAvatar",
  component: CustomAgentAvatar,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
};

export default meta;
type Story = StoryObj<typeof CustomAgentAvatar>;

// ---------------------------------------------------------------------------
// Default — falls back to letter from name
// ---------------------------------------------------------------------------

export const WithName: Story = {
  args: {
    name: "Research Assistant",
    size: 40,
  },
};

// ---------------------------------------------------------------------------
// Icon variants
// ---------------------------------------------------------------------------

export const WithIconSearch: Story = {
  args: {
    name: "Search Agent",
    iconName: "Search",
    size: 40,
  },
};

export const WithIconTerminal: Story = {
  args: {
    name: "Code Agent",
    iconName: "Terminal",
    size: 40,
  },
};

export const WithIconPen: Story = {
  args: {
    name: "Writer Agent",
    iconName: "Pen",
    size: 40,
  },
};

export const WithIconBarChart: Story = {
  args: {
    name: "Analytics Agent",
    iconName: "BarChart",
    size: 40,
  },
};

// ---------------------------------------------------------------------------
// Fallback — no name, no icon
// ---------------------------------------------------------------------------

export const NoNameNoIcon: Story = {
  args: {
    size: 40,
  },
};

// ---------------------------------------------------------------------------
// Sizes
// ---------------------------------------------------------------------------

export const Small: Story = {
  args: {
    name: "Tiny",
    iconName: "Info",
    size: 24,
  },
};

export const Large: Story = {
  args: {
    name: "Big Agent",
    iconName: "BooksStack",
    size: 64,
  },
};
