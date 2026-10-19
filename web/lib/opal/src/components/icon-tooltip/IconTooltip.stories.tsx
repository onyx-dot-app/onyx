import type { Meta, StoryObj } from "@storybook/react-vite";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { IconTooltip } from "@opal/components";
import { SvgAlertTriangle } from "@opal/icons";

const STATUSES = ["default", "info", "success", "warning", "error"] as const;

const meta: Meta<typeof IconTooltip> = {
  title: "opal/components/IconTooltip",
  component: IconTooltip,
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
type Story = StoryObj<typeof IconTooltip>;

export const Default: Story = {
  args: {
    tooltip: "Add the read:space scope, then re-run.",
  },
};

export const Statuses: Story = {
  render: () => (
    <div className="flex items-center gap-2">
      {STATUSES.map((status) => (
        <IconTooltip
          key={status}
          status={status}
          icon={status === "warning" ? SvgAlertTriangle : undefined}
          tooltip={status}
        />
      ))}
    </div>
  ),
};
