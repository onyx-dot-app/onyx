import React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import * as Illustrations from "@opal/illustrations";

const illustrations = Object.entries(Illustrations).map(
  ([name, Component]) => ({
    name: name.replace(/^Svg/, ""),
    Component,
  })
);

const meta: Meta = {
  title: "opal/illustrations/All Illustrations",
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj;

export const AllIllustrations: Story = {
  render: () => (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, 140px)",
        gap: 24,
      }}
    >
      {illustrations.map(({ name, Component }) => (
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
          <Component size={80} />
          <span style={{ fontSize: 11, textAlign: "center" }}>{name}</span>
        </div>
      ))}
    </div>
  ),
};
