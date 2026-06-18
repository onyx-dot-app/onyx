import type { Meta, StoryObj } from "@storybook/react";
import * as SettingsLayouts from "@opal/layouts/settings/components";
import { SvgSettings, SvgServer, SvgUser } from "@opal/icons";
import { Button } from "@opal/components";

const meta: Meta = {
  title: "Layouts/Settings",
  tags: ["autodocs"],
  parameters: { layout: "fullscreen" },
};

export default meta;
type Story = StoryObj;

export const Basic: Story = {
  render: () => (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgSettings}
        title="General Settings"
        description="Manage your preferences"
      />
      <SettingsLayouts.Body>
        <div className="h-96 bg-background-neutral-01 rounded-08 flex items-center justify-center">
          Page content
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  ),
};

export const WithActions: Story = {
  render: () => (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgServer}
        title="Data Sources"
        description="Manage connected data sources"
        rightChildren={<Button prominence="primary">Add source</Button>}
      />
      <SettingsLayouts.Body>
        <div className="h-96 bg-background-neutral-01 rounded-08 flex items-center justify-center">
          Page content
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  ),
};

export const WithBackButton: Story = {
  render: () => (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgUser}
        title="Edit User"
        description="Update user details"
        backButton
      />
      <SettingsLayouts.Body>
        <div className="h-96 bg-background-neutral-01 rounded-08 flex items-center justify-center">
          Page content
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  ),
};

export const WithDivider: Story = {
  render: () => (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgSettings}
        title="Settings"
        description="Manage your settings"
        divider
      />
      <SettingsLayouts.Body>
        <div className="h-96 bg-background-neutral-01 rounded-08 flex items-center justify-center">
          Page content
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  ),
};
