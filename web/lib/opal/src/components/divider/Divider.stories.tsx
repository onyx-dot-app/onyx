import React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { Divider } from "@opal/components/divider/components";

const meta: Meta<typeof Divider> = {
  title: "opal/components/Divider",
  component: Divider,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Divider>;

export const Plain: Story = {
  render: () => <Divider />,
};

export const WithTitle: Story = {
  render: () => <Divider title="Section" />,
};

export const WithDescription: Story = {
  render: () => (
    <Divider description="Additional configuration options for power users." />
  ),
};

export const Foldable: Story = {
  render: () => (
    <Divider title="Advanced Options" foldable defaultOpen={false}>
      <div style={{ padding: "0.5rem 0" }}>
        <p>This content is revealed when the divider is expanded.</p>
      </div>
    </Divider>
  ),
};

export const FoldableDefaultOpen: Story = {
  render: () => (
    <Divider title="Details" foldable defaultOpen>
      <div style={{ padding: "0.5rem 0" }}>
        <p>This starts open by default.</p>
      </div>
    </Divider>
  ),
};
