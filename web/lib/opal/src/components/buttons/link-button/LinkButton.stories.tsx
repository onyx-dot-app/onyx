import React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { LinkButton } from "@opal/components";

const meta: Meta<typeof LinkButton> = {
  title: "opal/components/LinkButton",
  component: LinkButton,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof LinkButton>;

// ─── Anchor mode ────────────────────────────────────────────────────────────

export const Default: Story = {
  render: () => <LinkButton href="/">Home</LinkButton>,
};

export const ExternalLink: Story = {
  render: () => (
    <LinkButton href="https://onyx.app" target="_blank">
      Onyx
    </LinkButton>
  ),
};

export const LongLabel: Story = {
  render: () => (
    <LinkButton href="https://docs.onyx.app" target="_blank">
      Go read the full Onyx documentation site
    </LinkButton>
  ),
};

// ─── Button mode ────────────────────────────────────────────────────────────

export const AsButton: Story = {
  render: () => (
    <LinkButton onClick={() => alert("clicked")}>Click me</LinkButton>
  ),
};

// ─── Disabled ───────────────────────────────────────────────────────────────

export const DisabledLink: Story = {
  render: () => (
    <LinkButton href="/" disabled>
      Disabled link
    </LinkButton>
  ),
};

export const DisabledButton: Story = {
  render: () => (
    <LinkButton onClick={() => alert("should not fire")} disabled>
      Disabled button
    </LinkButton>
  ),
};

// ─── Tooltip ────────────────────────────────────────────────────────────────

export const Tooltip: Story = {
  render: () => (
    <LinkButton href="/" tooltip="This is a tooltip">
      Hover me
    </LinkButton>
  ),
};

export const TooltipSides: Story = {
  render: () => (
    <div className="flex flex-col gap-8 p-16">
      <LinkButton href="/" tooltip="Tooltip on top" tooltipSide="top">
        top
      </LinkButton>
      <LinkButton href="/" tooltip="Tooltip on right" tooltipSide="right">
        right
      </LinkButton>
      <LinkButton href="/" tooltip="Tooltip on bottom" tooltipSide="bottom">
        bottom
      </LinkButton>
      <LinkButton href="/" tooltip="Tooltip on left" tooltipSide="left">
        left
      </LinkButton>
    </div>
  ),
};

// ─── Inline in prose ────────────────────────────────────────────────────────

export const InlineInProse: Story = {
  render: () => (
    <p style={{ maxWidth: "36rem", lineHeight: 1.7 }}>
      Modifying embedding settings requires a full re-index of all documents and
      may take hours or days depending on corpus size.{" "}
      <LinkButton href="https://docs.onyx.app" target="_blank">
        Learn more
      </LinkButton>
      .
    </p>
  ),
};
