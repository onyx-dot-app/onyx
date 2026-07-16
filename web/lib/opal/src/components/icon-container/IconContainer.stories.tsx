import type { Meta, StoryObj } from "@storybook/react";
import { IconContainer, type IconContainerSize } from "@opal/components";
import { SvgSearch, SvgUser } from "@opal/icons";
import { SvgSlack } from "@opal/logos";

const meta: Meta<typeof IconContainer> = {
  title: "opal/components/IconContainer",
  component: IconContainer,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof IconContainer>;

const SIZES: IconContainerSize[] = [
  "secondary",
  "main-ui",
  "main-content",
  "section",
  "sub-headline",
];

export const Icon: Story = {
  render: () => (
    <div className="flex items-center gap-2">
      {SIZES.map((size) => (
        <IconContainer key={size} size={size} icon={SvgSearch} />
      ))}
    </div>
  ),
};

export const Entity: Story = {
  render: () => (
    <div className="flex items-center gap-2">
      {SIZES.map((size) => (
        <IconContainer key={size} size={size} type="entity" icon={SvgSearch} />
      ))}
    </div>
  ),
};

export const AvatarUser: Story = {
  render: () => (
    <div className="flex items-center gap-2">
      {SIZES.map((size) => (
        <IconContainer key={size} size={size} avatar="user" name="Taylor" />
      ))}
    </div>
  ),
};

export const AvatarIcon: Story = {
  render: () => (
    <div className="flex items-center gap-2 rounded-08 bg-background-tint-02 p-2">
      {SIZES.map((size) => (
        <IconContainer key={size} size={size} avatar="icon" icon={SvgUser} />
      ))}
    </div>
  ),
};

export const Logo: Story = {
  render: () => (
    <div className="flex items-center gap-2">
      {SIZES.map((size) => (
        <IconContainer key={size} size={size} icon={SvgSlack} />
      ))}
    </div>
  ),
};
