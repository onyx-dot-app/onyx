import type { Meta, StoryObj } from "@storybook/react";
import LineItem from "./LineItem";
import {
  SvgUser,
  SvgSettings,
  SvgTrash,
  SvgFolder,
  SvgCheck,
  SvgSearch,
} from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
// TODO(@raunakab): migrate this `refresh-components/Text` to `@opal/components` Text
import Text from "@/refresh-components/texts/Text";

const meta: Meta<typeof LineItem> = {
  title: "refresh-components/buttons/LineItem",
  component: LineItem,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <div style={{ width: 300 }}>
          <Story />
        </div>
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof LineItem>;

export const Default: Story = {
  args: {
    icon: SvgUser,
    children: "Profile Settings",
  },
};

export const WithDescription: Story = {
  args: {
    icon: SvgSettings,
    children: "Settings",
    description: "Manage your account settings",
  },
};

export const Selected: Story = {
  args: {
    icon: SvgCheck,
    children: "Active Item",
    selected: true,
  },
};

export const SelectedEmphasized: Story = {
  args: {
    icon: SvgFolder,
    children: "Selected Folder",
    selected: true,
    emphasized: true,
  },
};

export const Danger: Story = {
  args: {
    icon: SvgTrash,
    children: "Delete Account",
    danger: true,
  },
};

export const Action: Story = {
  args: {
    icon: SvgSearch,
    children: "Search Results",
    action: true,
  },
};

export const Muted: Story = {
  args: {
    icon: SvgFolder,
    children: "Secondary Item",
    muted: true,
  },
};

export const Strikethrough: Story = {
  args: {
    icon: SvgFolder,
    children: "Archived Feature",
    strikethrough: true,
  },
};

export const WithRightChildren: Story = {
  args: {
    icon: SvgSettings,
    children: "Keyboard Shortcuts",
    rightChildren: (
      <Text as="p" secondaryBody text03>
        Cmd+K
      </Text>
    ),
  },
};

export const MenuExample: Story = {
  render: () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <LineItem icon={SvgUser}>Profile</LineItem>
      <LineItem icon={SvgSettings} description="Manage your preferences">
        Settings
      </LineItem>
      <LineItem icon={SvgFolder} selected emphasized>
        Documents
      </LineItem>
      <LineItem icon={SvgSearch} action>
        Search
      </LineItem>
      <LineItem icon={SvgFolder} muted>
        Archived
      </LineItem>
      <LineItem icon={SvgTrash} danger>
        Delete
      </LineItem>
    </div>
  ),
};
