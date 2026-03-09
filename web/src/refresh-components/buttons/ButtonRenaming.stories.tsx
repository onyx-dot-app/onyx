import React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import ButtonRenaming from "./ButtonRenaming";

const meta: Meta<typeof ButtonRenaming> = {
  title: "refresh-components/buttons/ButtonRenaming",
  component: ButtonRenaming,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <div
        style={{
          width: 260,
          padding: 8,
          background: "var(--background-neutral-01)",
          borderRadius: 8,
        }}
      >
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof ButtonRenaming>;

export const Default: Story = {
  args: {
    initialName: "My Chat Session",
    onRename: async (name: string) => {
      console.log("Renamed to:", name);
    },
    onClose: () => {
      console.log("Closed");
    },
  },
};

export const EmptyName: Story = {
  args: {
    initialName: null,
    onRename: async (name: string) => {
      console.log("Renamed to:", name);
    },
    onClose: () => {
      console.log("Closed");
    },
  },
};

export const LongName: Story = {
  args: {
    initialName: "This is a very long chat session name that should overflow",
    onRename: async (name: string) => {
      console.log("Renamed to:", name);
    },
    onClose: () => {
      console.log("Closed");
    },
  },
};
