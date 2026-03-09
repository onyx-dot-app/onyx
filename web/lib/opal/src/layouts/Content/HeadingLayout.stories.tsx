import type { Meta, StoryObj } from "@storybook/react";
import { HeadingLayout } from "./HeadingLayout";
import { SvgSettings, SvgStar } from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta = {
  title: "Layouts/HeadingLayout",
  component: HeadingLayout,
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
} satisfies Meta<typeof HeadingLayout>;

export default meta;

type Story = StoryObj<typeof meta>;

// ---------------------------------------------------------------------------
// Size presets
// ---------------------------------------------------------------------------

export const Headline: Story = {
  args: {
    sizePreset: "headline",
    title: "Welcome to Onyx",
    description: "Your enterprise search and AI assistant platform.",
  },
};

export const Section: Story = {
  args: {
    sizePreset: "section",
    title: "Configuration",
  },
};

// ---------------------------------------------------------------------------
// With icon
// ---------------------------------------------------------------------------

export const WithIcon: Story = {
  args: {
    sizePreset: "headline",
    title: "Settings",
    icon: SvgSettings,
  },
};

export const SectionWithIcon: Story = {
  args: {
    sizePreset: "section",
    variant: "section",
    title: "Favorites",
    icon: SvgStar,
  },
};

// ---------------------------------------------------------------------------
// Variants
// ---------------------------------------------------------------------------

export const SectionVariant: Story = {
  args: {
    sizePreset: "headline",
    variant: "section",
    title: "Inline Icon Heading",
    icon: SvgSettings,
  },
};

// ---------------------------------------------------------------------------
// Editable
// ---------------------------------------------------------------------------

export const Editable: Story = {
  args: {
    sizePreset: "headline",
    title: "Click to edit me",
    editable: true,
  },
};

export const EditableSection: Story = {
  args: {
    sizePreset: "section",
    title: "Editable Section Title",
    editable: true,
    description: "This title can be edited inline.",
  },
};
