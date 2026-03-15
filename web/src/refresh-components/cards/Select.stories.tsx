import React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import Select from "./Select";
import { SvgSettings, SvgFolder, SvgSearch } from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof Select> = {
  title: "refresh-components/cards/Select",
  component: Select,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <div style={{ maxWidth: 500 }}>
          <Story />
        </div>
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof Select>;

export const Disconnected: Story = {
  args: {
    icon: SvgFolder,
    title: "Google Drive",
    description: "Connect to sync your files",
    status: "disconnected",
    onConnect: () => {},
  },
};

export const Connected: Story = {
  args: {
    icon: SvgFolder,
    title: "Google Drive",
    description: "Connected and syncing",
    status: "connected",
    onSelect: () => {},
    onEdit: () => {},
  },
};

export const Selected: Story = {
  args: {
    icon: SvgFolder,
    title: "Google Drive",
    description: "Currently the default source",
    status: "selected",
    onDeselect: () => {},
    onEdit: () => {},
  },
};

export const DisabledState: Story = {
  args: {
    icon: SvgFolder,
    title: "Google Drive",
    description: "Not available on this plan",
    status: "disconnected",
    disabled: true,
    onConnect: () => {},
  },
};

export const MediumSize: Story = {
  args: {
    icon: SvgSearch,
    title: "Elastic Search",
    description: "Search engine connector",
    status: "connected",
    medium: true,
    onSelect: () => {},
  },
};

export const CustomLabels: Story = {
  args: {
    icon: SvgSettings,
    title: "Custom LLM",
    description: "Your custom model endpoint",
    status: "connected",
    connectLabel: "Link",
    selectLabel: "Make Primary",
    selectedLabel: "Primary Model",
    onSelect: () => {},
    onEdit: () => {},
  },
};

export const AllStates: Story = {
  render: () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <Select
        icon={SvgFolder}
        title="Google Drive"
        description="Connect to sync your files"
        status="disconnected"
        onConnect={() => {}}
      />
      <Select
        icon={SvgSearch}
        title="Confluence"
        description="Connected and syncing"
        status="connected"
        onSelect={() => {}}
        onEdit={() => {}}
      />
      <Select
        icon={SvgSettings}
        title="Notion"
        description="Currently the default source"
        status="selected"
        onDeselect={() => {}}
        onEdit={() => {}}
      />
      <Select
        icon={SvgFolder}
        title="Sharepoint"
        description="Not available"
        status="disconnected"
        disabled
        onConnect={() => {}}
      />
    </div>
  ),
};
