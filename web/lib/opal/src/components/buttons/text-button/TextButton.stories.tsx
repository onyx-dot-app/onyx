import React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { TextButton } from "@opal/components";
import { SvgPlus, SvgArrowRight, SvgSettings } from "@opal/icons";

const meta: Meta<typeof TextButton> = {
  title: "opal/components/TextButton",
  component: TextButton,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof TextButton>;

export const Default: Story = {
  args: {
    children: "Text button",
  },
};

const VARIANTS = ["default", "action", "danger"] as const;
const PROMINENCES = ["primary", "secondary", "tertiary", "internal"] as const;

export const VariantProminenceGrid: Story = {
  render: () => (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "auto repeat(4, 1fr)",
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
            <TextButton
              key={`${variant}-${prominence}`}
              variant={variant}
              prominence={prominence}
            >
              {`${variant} ${prominence}`}
            </TextButton>
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
        <TextButton key={size} size={size} icon={SvgPlus}>
          {size}
        </TextButton>
      ))}
    </div>
  ),
};

export const Disabled: Story = {
  args: {
    disabled: true,
    children: "Disabled",
  },
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

export const NoBackgroundEvenOnPrimary: Story = {
  render: () => (
    <div style={{ display: "flex", gap: 12 }}>
      <TextButton variant="default" prominence="primary">
        Primary
      </TextButton>
      <TextButton variant="action" prominence="primary">
        Action primary
      </TextButton>
      <TextButton variant="danger" prominence="primary">
        Danger primary
      </TextButton>
    </div>
  ),
};

export const InlineInProse: Story = {
  render: () => (
    <p style={{ maxWidth: "36rem", lineHeight: 1.7 }}>
      You can undo this action within the next 30 seconds.{" "}
      <TextButton onClick={() => alert("undone")}>Undo</TextButton>.
    </p>
  ),
};
