import type { Meta, StoryObj } from "@storybook/react";
import { LabelLayout } from "./LabelLayout";
import { SvgSettings, SvgStar } from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta = {
  title: "Layouts/LabelLayout",
  component: LabelLayout,
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
} satisfies Meta<typeof LabelLayout>;

export default meta;

type Story = StoryObj<typeof meta>;

// ---------------------------------------------------------------------------
// Size presets
// ---------------------------------------------------------------------------

export const MainContent: Story = {
  args: {
    sizePreset: "main-content",
    title: "Display Name",
  },
};

export const MainUi: Story = {
  args: {
    sizePreset: "main-ui",
    title: "Email Address",
  },
};

export const SecondaryPreset: Story = {
  args: {
    sizePreset: "secondary",
    title: "API Key",
  },
};

// ---------------------------------------------------------------------------
// With description
// ---------------------------------------------------------------------------

export const WithDescription: Story = {
  args: {
    sizePreset: "main-content",
    title: "Workspace Name",
    description: "The name displayed across your organization.",
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
// Optional
// ---------------------------------------------------------------------------

export const Optional: Story = {
  args: {
    sizePreset: "main-content",
    title: "Phone Number",
    optional: true,
  },
};

// ---------------------------------------------------------------------------
// Aux icons
// ---------------------------------------------------------------------------

export const AuxInfoGray: Story = {
  args: {
    sizePreset: "main-content",
    title: "Connection Status",
    auxIcon: "info-gray",
  },
};

export const AuxWarning: Story = {
  args: {
    sizePreset: "main-content",
    title: "Rate Limit",
    auxIcon: "warning",
  },
};

export const AuxError: Story = {
  args: {
    sizePreset: "main-content",
    title: "API Key",
    auxIcon: "error",
  },
};

// ---------------------------------------------------------------------------
// With tag
// ---------------------------------------------------------------------------

export const WithTag: Story = {
  args: {
    sizePreset: "main-ui",
    title: "Knowledge Graph",
    tag: { title: "Beta", color: "blue" },
  },
};

// ---------------------------------------------------------------------------
// Editable
// ---------------------------------------------------------------------------

export const Editable: Story = {
  args: {
    sizePreset: "main-ui",
    title: "Click to edit",
    editable: true,
  },
};

// ---------------------------------------------------------------------------
// Combined
// ---------------------------------------------------------------------------

export const FullFeatured: Story = {
  args: {
    sizePreset: "main-content",
    title: "Custom Field",
    icon: SvgStar,
    description: "A custom field with all extras enabled.",
    optional: true,
    auxIcon: "info-blue",
    tag: { title: "New", color: "green" },
    editable: true,
  },
};
