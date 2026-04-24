import type { Meta, StoryObj } from "@storybook/react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type { Decorator } from "@storybook/react";
import { Disabled } from "@opal/core";
import { Card, Button } from "@opal/components";

const withTooltipProvider: Decorator = (Story) => (
  <TooltipPrimitive.Provider>
    <Story />
  </TooltipPrimitive.Provider>
);

const meta: Meta<typeof Disabled> = {
  title: "opal/core/Disabled",
  component: Disabled,
  tags: ["autodocs"],
  decorators: [withTooltipProvider],
};

export default meta;
type Story = StoryObj<typeof Disabled>;

const SampleContent = () => (
  <Card border="solid" padding="md">
    <div className="flex flex-col gap-2">
      <p className="text-sm font-medium">Card Title</p>
      <p className="text-xs text-text-03">Some content that can be disabled.</p>
      <Button prominence="secondary" size="sm">
        Action
      </Button>
    </div>
  </Card>
);

export const Enabled: Story = {
  render: () => (
    <div className="w-80">
      <Disabled disabled={false}>
        <SampleContent />
      </Disabled>
    </div>
  ),
};

export const DisabledState: Story = {
  render: () => (
    <div className="w-80">
      <Disabled disabled>
        <SampleContent />
      </Disabled>
    </div>
  ),
};

export const WithTooltip: Story = {
  render: () => (
    <div className="w-80">
      <Disabled disabled tooltip="This feature requires a Pro plan">
        <SampleContent />
      </Disabled>
    </div>
  ),
};

export const TooltipSides: Story = {
  render: () => (
    <div className="flex flex-col gap-8 items-center py-16">
      {(["top", "right", "bottom", "left"] as const).map((side) => (
        <Disabled
          key={side}
          disabled
          tooltip={`Tooltip on ${side}`}
          tooltipSide={side}
        >
          <Card border="solid" padding="sm">
            <p className="text-sm">tooltipSide: {side}</p>
          </Card>
        </Disabled>
      ))}
    </div>
  ),
};

export const WithAllowClick: Story = {
  render: () => (
    <div className="w-80">
      <Disabled disabled allowClick>
        <Card border="solid" padding="md">
          <p className="text-sm">
            Disabled visuals, but pointer events are still active.
          </p>
          <Button
            prominence="tertiary"
            size="sm"
            onClick={() => alert("Clicked!")}
          >
            Click me
          </Button>
        </Card>
      </Disabled>
    </div>
  ),
};

export const Comparison: Story = {
  render: () => (
    <div className="flex gap-4">
      <div className="flex flex-col gap-2 w-60">
        <p className="text-xs font-medium">Enabled</p>
        <Disabled disabled={false}>
          <SampleContent />
        </Disabled>
      </div>
      <div className="flex flex-col gap-2 w-60">
        <p className="text-xs font-medium">Disabled</p>
        <Disabled disabled>
          <SampleContent />
        </Disabled>
      </div>
      <div className="flex flex-col gap-2 w-60">
        <p className="text-xs font-medium">Disabled + Tooltip</p>
        <Disabled disabled tooltip="Not available right now">
          <SampleContent />
        </Disabled>
      </div>
    </div>
  ),
};
