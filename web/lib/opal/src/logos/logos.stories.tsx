import React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import * as Logos from "@opal/logos";

const logos = Object.entries(Logos).map(([name, Component]) => ({
  name: name.replace(/^Svg/, ""),
  Component,
}));

const meta: Meta = {
  title: "opal/logos/All Logos",
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj;

export const AllLogos: Story = {
  render: () => (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, 120px)",
        gap: 16,
      }}
    >
      {logos.map(({ name, Component }) => (
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
          <Component size={32} />
          <span style={{ fontSize: 11, textAlign: "center" }}>{name}</span>
        </div>
      ))}
    </div>
  ),
};
