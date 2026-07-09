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

export const Editable: Story = {
  args: {
    title: "Label",
    onRemove: () => {},
  },
};

export const EditableMd: Story = {
  render: () => (
    <div className="flex items-center gap-2">
      <Tag title="Default" size="md" onRemove={() => {}} />
      <Tag
        title="With icon"
        size="md"
        icon={SvgAlertCircle}
        onRemove={() => {}}
      />
      <Tag title="Label" size="md" value="Value" onRemove={() => {}} />
      <Tag
        title="A very long label that gets capped at 160px"
        size="md"
        onRemove={() => {}}
      />
      <Tag title="Error" size="md" error onRemove={() => {}} />
      <Tag title="Disabled" size="md" disabled onRemove={() => {}} />
    </div>
  ),
};

export const EditableSm: Story = {
  render: () => (
    <div className="flex items-center gap-2">
      <Tag title="Default" onRemove={() => {}} />
      <Tag title="With icon" icon={SvgAlertCircle} onRemove={() => {}} />
      <Tag
        title="A very long label that gets capped at 120px"
        onRemove={() => {}}
      />
      <Tag title="Disabled" disabled onRemove={() => {}} />
    </div>
  ),
};

export const TruncatedWithTooltip: Story = {
  args: {
    title: "A very long metadata label that gets capped",
    truncate: true,
  },
};
