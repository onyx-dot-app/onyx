import React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import Divider from "./Divider";
import { SvgSettings } from "@opal/icons";

const meta: Meta<typeof Divider> = {
  title: "refresh-components/Divider",
  component: Divider,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Divider>;

export const SimpleLine: Story = {
  args: {},
};

export const WithTitle: Story = {
  args: {
    showTitle: true,
    text: "Section Title",
  },
};

export const WithTitleAndDescription: Story = {
  args: {
    showTitle: true,
    text: "Advanced Settings",
    description: "Configure additional options for this section.",
    showDescription: true,
  },
};

export const WithInfoText: Story = {
  args: {
    showTitle: true,
    text: "Items",
    infoText: "3 items",
    showInfo: true,
  },
};

function FoldableDividerDemo() {
  const [expanded, setExpanded] = React.useState(false);
  return (
    <div style={{ width: 400 }}>
      <Divider
        showTitle
        text="Click to toggle"
        foldable
        expanded={expanded}
        onClick={() => setExpanded(!expanded)}
      />
      {expanded && (
        <div style={{ padding: 12 }}>Expanded content goes here.</div>
      )}
    </div>
  );
}

export const Foldable: Story = {
  render: () => <FoldableDividerDemo />,
};

export const WithIcon: Story = {
  args: {
    showTitle: true,
    text: "Settings",
    icon: SvgSettings,
  },
};

export const Highlighted: Story = {
  args: {
    showTitle: true,
    text: "Active Section",
    foldable: true,
    expanded: false,
    isHighlighted: true,
  },
};

export const NoDividerLine: Story = {
  args: {
    showTitle: true,
    text: "No Lines",
    dividerLine: false,
  },
};
