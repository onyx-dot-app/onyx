import type { Meta, StoryObj } from "@storybook/react";
import { CardHeaderLayout } from "@opal/layouts";
import { Button } from "@opal/components";
import {
  SvgArrowExchange,
  SvgCheckSquare,
  SvgGlobe,
  SvgSettings,
  SvgUnplug,
} from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type { Decorator } from "@storybook/react";

const withTooltipProvider: Decorator = (Story) => (
  <TooltipPrimitive.Provider>
    <Story />
  </TooltipPrimitive.Provider>
);

const meta = {
  title: "Layouts/CardHeaderLayout",
  component: CardHeaderLayout,
  tags: ["autodocs"],
  decorators: [withTooltipProvider],
  parameters: {
    layout: "centered",
  },
} satisfies Meta<typeof CardHeaderLayout>;

export default meta;

type Story = StoryObj<typeof meta>;

// ---------------------------------------------------------------------------
// Stories
// ---------------------------------------------------------------------------

export const Default: Story = {
  render: () => (
    <div className="w-[28rem] border rounded-16">
      <CardHeaderLayout
        sizePreset="main-ui"
        variant="section"
        icon={SvgGlobe}
        title="Google Search"
        description="Web search provider"
        rightChildren={
          <Button prominence="tertiary" rightIcon={SvgArrowExchange}>
            Connect
          </Button>
        }
      />
    </div>
  ),
};

export const WithBothSlots: Story = {
  render: () => (
    <div className="w-[28rem] border rounded-16">
      <CardHeaderLayout
        sizePreset="main-ui"
        variant="section"
        icon={SvgGlobe}
        title="Google Search"
        description="Currently the default provider."
        rightChildren={
          <Button variant="action" prominence="tertiary" icon={SvgCheckSquare}>
            Current Default
          </Button>
        }
        bottomRightChildren={
          <>
            <Button
              icon={SvgUnplug}
              tooltip="Disconnect"
              prominence="tertiary"
              size="sm"
            />
            <Button
              icon={SvgSettings}
              tooltip="Edit"
              prominence="tertiary"
              size="sm"
            />
          </>
        }
      />
    </div>
  ),
};

export const RightChildrenOnly: Story = {
  render: () => (
    <div className="w-[28rem] border rounded-16">
      <CardHeaderLayout
        sizePreset="main-ui"
        variant="section"
        icon={SvgGlobe}
        title="OpenAI"
        description="Not configured"
        rightChildren={
          <Button prominence="tertiary" rightIcon={SvgArrowExchange}>
            Connect
          </Button>
        }
      />
    </div>
  ),
};

export const NoRightChildren: Story = {
  render: () => (
    <div className="w-[28rem] border rounded-16">
      <CardHeaderLayout
        sizePreset="main-ui"
        variant="section"
        icon={SvgGlobe}
        title="Section Header"
        description="No actions on the right."
      />
    </div>
  ),
};

export const LongContent: Story = {
  render: () => (
    <div className="w-[28rem] border rounded-16">
      <CardHeaderLayout
        sizePreset="main-ui"
        variant="section"
        icon={SvgGlobe}
        title="Very Long Provider Name That Should Truncate"
        description="This is a much longer description that tests how the layout handles overflow when the content area needs to shrink."
        rightChildren={
          <Button variant="action" prominence="tertiary" icon={SvgCheckSquare}>
            Current Default
          </Button>
        }
        bottomRightChildren={
          <>
            <Button
              icon={SvgUnplug}
              prominence="tertiary"
              size="sm"
              tooltip="Disconnect"
            />
            <Button
              icon={SvgSettings}
              prominence="tertiary"
              size="sm"
              tooltip="Edit"
            />
          </>
        }
      />
    </div>
  ),
};
