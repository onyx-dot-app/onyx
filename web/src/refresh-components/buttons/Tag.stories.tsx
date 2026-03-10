import type { Meta, StoryObj } from "@storybook/react";
import Tag from "./Tag";
import { SvgFilter, SvgUser, SvgFolder } from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof Tag> = {
  title: "refresh-components/buttons/Tag",
  component: Tag,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <Story />
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof Tag>;

export const Default: Story = {
  args: {
    label: "Label",
  },
};

export const DisplayVariant: Story = {
  args: {
    label: "Display Tag",
    variant: "display",
  },
};

export const EditableVariant: Story = {
  args: {
    label: "Editable Tag",
    variant: "editable",
  },
};

export const WithIcon: Story = {
  args: {
    label: "With Icon",
    icon: SvgFilter,
  },
};

export const Removable: Story = {
  args: {
    label: "Removable",
    variant: "editable",
    onRemove: () => {},
  },
};

export const Clickable: Story = {
  args: {
    label: "Click Me",
    onClick: () => {},
  },
};

export const WithIconAndRemove: Story = {
  args: {
    label: "Filter: Active",
    variant: "editable",
    icon: SvgFilter,
    onRemove: () => {},
  },
};

export const TagGroup: Story = {
  render: () => (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
      <Tag label="React" variant="display" />
      <Tag label="TypeScript" variant="display" icon={SvgFolder} />
      <Tag
        label="Active Filter"
        variant="editable"
        icon={SvgFilter}
        onRemove={() => {}}
      />
      <Tag
        label="John Doe"
        variant="editable"
        icon={SvgUser}
        onRemove={() => {}}
      />
      <Tag label="Clickable" onClick={() => {}} />
    </div>
  ),
};
