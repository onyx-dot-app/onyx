import React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import * as Icons from "@opal/icons";

const icons = Object.entries(Icons).map(([name, Component]) => ({
  name: name.replace(/^Svg/, ""),
  Component,
}));

const meta: Meta = {
  title: "opal/icons/All Icons",
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj;

export const AllIcons: Story = {
  render: () => (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, 100px)",
        gap: 16,
      }}
    >
      {icons.map(({ name, Component }) => (
        <div
          key={name}
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 8,
            padding: 8,
          }}
        >
          <Component size={24} />
          <span style={{ fontSize: 11, textAlign: "center" }}>{name}</span>
        </div>
      ))}
    </div>
  ),
};
