import type { Meta, StoryObj } from "@storybook/react-vite";
import { Chip, Popover } from "@opal/components";
import {
  SvgAlertCircle,
  SvgAlertTriangle,
  SvgCheckCircle,
  SvgUsers,
} from "@opal/icons";

const meta: Meta<typeof Chip> = {
  title: "opal/components/Chip",
  component: Chip,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Chip>;

export const Static: Story = {
  args: {
    icon: SvgUsers,
    title: "Admins",
  },
};

export const Removable: Story = {
  render: () => (
    <div className="flex items-center gap-2">
      <Chip title="Default" onRemove={() => {}} />
      <Chip title="With icon" icon={SvgUsers} onRemove={() => {}} />
      <Chip title="Error" error onRemove={() => {}} />
      <Chip
        title="A removable title that is far too long to fit"
        onRemove={() => {}}
      />
      <Chip
        title="Disabled"
        disabled
        tooltip="Why it is disabled"
        onRemove={() => {}}
      />
    </div>
  ),
};

export const Truncated: Story = {
  args: {
    title: "A very long chip label that gets capped",
    truncate: true,
  },
};

export const Toggle: Story = {
  render: () => (
    <div className="flex items-center gap-2">
      <Chip
        icon={SvgCheckCircle}
        iconColor="green"
        title="12"
        aria-pressed={false}
        onClick={() => {}}
      />
      <Chip
        icon={SvgAlertCircle}
        iconColor="red"
        title="3"
        aria-pressed
        onClick={() => {}}
      />
    </div>
  ),
};

export const PopoverTrigger: Story = {
  render: () => (
    <div className="flex items-center gap-2">
      <Popover>
        <Popover.Trigger asChild>
          <Chip
            icon={SvgAlertCircle}
            iconColor="red"
            title="Stack Trace"
            onClick={() => {}}
          />
        </Popover.Trigger>
        <Popover.Content width={60}>
          <div className="p-2">Popover content</div>
        </Popover.Content>
      </Popover>
      <Popover defaultOpen>
        <Popover.Trigger asChild>
          <Chip
            icon={SvgAlertTriangle}
            iconColor="orange"
            title="3 failed"
            onClick={() => {}}
          />
        </Popover.Trigger>
        <Popover.Content width={60}>
          <div className="p-2">Open: the chip shows its hover look</div>
        </Popover.Content>
      </Popover>
    </div>
  ),
};
