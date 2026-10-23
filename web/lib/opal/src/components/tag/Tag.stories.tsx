import type { Meta, StoryObj } from "@storybook/react-vite";
import { Tag } from "@opal/components";
import {
  SvgAlertCircle,
  SvgAlertTriangle,
  SvgCheckCircle,
  SvgPause,
  SvgRefreshCw,
} from "@opal/icons";

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

export const Status: Story = {
  render: () => (
    <div className="flex items-center gap-2">
      <Tag icon={SvgRefreshCw} title="Indexing" color="blue" variant="status" />
      <Tag
        icon={SvgCheckCircle}
        title="Synced"
        color="green"
        variant="status"
      />
      <Tag icon={SvgPause} title="Paused" color="amber" variant="status" />
      <Tag icon={SvgAlertCircle} title="Failed" color="red" variant="status" />
    </div>
  ),
};

export const Count: Story = {
  render: () => (
    <div className="flex items-center gap-2">
      <Tag icon={SvgAlertTriangle} title="12" color="orange" variant="count" />
      <Tag icon={SvgAlertCircle} title="4" color="red" variant="count" />
    </div>
  ),
};
