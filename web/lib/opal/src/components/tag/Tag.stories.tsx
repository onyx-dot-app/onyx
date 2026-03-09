import type { Meta, StoryObj } from "@storybook/react";
import { Tag } from "@opal/components";
import { SvgAlertCircle } from "@opal/icons";

const TAG_COLORS = ["green", "purple", "blue", "gray", "amber"] as const;

const meta: Meta<typeof Tag> = {
  title: "opal/components/Tag",
  component: Tag,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Tag>;

export const Default: Story = {
  args: {
    title: "Label",
  },
};

export const AllColors: Story = {
  render: () => (
    <div className="flex items-center gap-2">
      {TAG_COLORS.map((color) => (
        <Tag key={color} title={color} color={color} />
      ))}
    </div>
  ),
};

export const WithIcon: Story = {
  args: {
    title: "Alert",
    icon: SvgAlertCircle,
  },
};

export const AllColorsWithIcon: Story = {
  render: () => (
    <div className="flex items-center gap-2">
      {TAG_COLORS.map((color) => (
        <Tag key={color} title={color} color={color} icon={SvgAlertCircle} />
      ))}
    </div>
  ),
};
