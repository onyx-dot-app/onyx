import type { Meta, StoryObj } from "@storybook/react";
import ButtonTile from "./ButtonTile";
import { SvgArrowRight, SvgPlus, SvgSettings, SvgSearch } from "@opal/icons";

const meta: Meta<typeof ButtonTile> = {
  title: "refresh-components/tiles/ButtonTile",
  component: ButtonTile,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <div style={{ maxWidth: 300 }}>
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof ButtonTile>;

export const Default: Story = {
  args: {
    title: "Create New",
    description: "Start from scratch",
    icon: SvgArrowRight,
    onClick: () => {},
  },
};

export const TitleOnly: Story = {
  args: {
    title: "Quick Action",
    icon: SvgPlus,
    onClick: () => {},
  },
};

export const DescriptionOnly: Story = {
  args: {
    description: "Click to configure settings",
    icon: SvgSettings,
    onClick: () => {},
  },
};

export const NoIcon: Story = {
  args: {
    title: "Simple Tile",
    description: "Without an icon",
    onClick: () => {},
  },
};

export const Disabled: Story = {
  args: {
    title: "Unavailable",
    description: "This feature is not enabled",
    icon: SvgSettings,
    disabled: true,
  },
};

export const TileGrid: Story = {
  render: () => (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 8,
        maxWidth: 500,
      }}
    >
      <ButtonTile
        title="Search"
        description="Find documents"
        icon={SvgSearch}
        onClick={() => {}}
      />
      <ButtonTile
        title="Create"
        description="New document"
        icon={SvgPlus}
        onClick={() => {}}
      />
      <ButtonTile
        title="Settings"
        description="Configure"
        icon={SvgSettings}
        onClick={() => {}}
      />
      <ButtonTile
        title="Disabled"
        description="Not available"
        icon={SvgArrowRight}
        disabled
      />
    </div>
  ),
};
