import React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { Button } from "@opal/components";
import { SvgPlus, SvgArrowRight, SvgSettings } from "@opal/icons";

const meta: Meta<typeof Button> = {
  title: "opal/components/Button",
  component: Button,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Button>;

export const Default: Story = {
  args: {
    children: "Button",
    variant: "default",
    prominence: "primary",
  },
};

const VARIANTS = ["default", "action", "danger"] as const;
const PROMINENCES = ["primary", "secondary", "tertiary"] as const;

export const VariantProminenceGrid: Story = {
  render: () => (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "auto repeat(3, 1fr)",
        gap: 12,
        alignItems: "center",
      }}
    >
      {/* Header row */}
      <div />
      {PROMINENCES.map((p) => (
        <div
          key={p}
          style={{
            fontWeight: 600,
            textAlign: "center",
            textTransform: "capitalize",
          }}
        >
          {p}
        </div>
      ))}

      {/* Variant rows */}
      {VARIANTS.map((variant) => (
        <React.Fragment key={variant}>
          <div style={{ fontWeight: 600, textTransform: "capitalize" }}>
            {variant}
          </div>
          {PROMINENCES.map((prominence) => (
            <Button
              key={`${variant}-${prominence}`}
              variant={variant}
              prominence={prominence}
            >
              {`${variant} ${prominence}`}
            </Button>
          ))}
        </React.Fragment>
      ))}
    </div>
  ),
};

export const WithLeftIcon: Story = {
  args: {
    icon: SvgPlus,
    children: "Add item",
  },
};

export const WithRightIcon: Story = {
  args: {
    rightIcon: SvgArrowRight,
    children: "Continue",
  },
};

export const IconOnly: Story = {
  args: {
    icon: SvgSettings,
  },
};

export const Sizes: Story = {
  render: () => (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      {(["lg", "md", "sm", "xs", "2xs", "fit"] as const).map((size) => (
        <Button key={size} size={size} icon={SvgPlus}>
          {size}
        </Button>
      ))}
    </div>
  ),
};

export const Foldable: Story = {
  args: {
    foldable: true,
    icon: SvgPlus,
    children: "Add item",
  },
};

export const Disabled: Story = {
  args: {
    disabled: true,
    children: "Disabled",
  },
};

export const WidthFull: Story = {
  args: {
    width: "full",
    children: "Full width",
  },
  decorators: [
    (Story) => (
      <div style={{ width: 400 }}>
        <Story />
      </div>
    ),
  ],
};

export const AsLink: Story = {
  args: {
    href: "https://example.com",
    children: "Visit site",
    rightIcon: SvgArrowRight,
  },
};

export const WithTooltip: Story = {
  args: {
    icon: SvgSettings,
    tooltip: "Open settings",
    tooltipSide: "bottom",
  },
};

export const ResponsiveHideText: Story = {
  args: {
    icon: SvgPlus,
    children: "Create",
    responsiveHideText: true,
  },
};

export const InternalProminence: Story = {
  args: {
    variant: "default",
    prominence: "internal",
    children: "Internal",
  },
};
