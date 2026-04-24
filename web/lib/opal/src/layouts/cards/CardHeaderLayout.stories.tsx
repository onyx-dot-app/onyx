import type { Meta, StoryObj } from "@storybook/react";
import { Card, ContentAction } from "@opal/layouts";
import { Button } from "@opal/components";
import {
  SvgArrowExchange,
  SvgCheckSquare,
  SvgGlobe,
  SvgSettings,
  SvgUnplug,
} from "@opal/icons";

const meta = {
  title: "Layouts/Card.Header",
  component: Card.Header,
  tags: ["autodocs"],

  parameters: {
    layout: "centered",
  },
} satisfies Meta<typeof Card.Header>;

export default meta;

type Story = StoryObj<typeof meta>;

// ---------------------------------------------------------------------------
// Stories
// ---------------------------------------------------------------------------

export const Default: Story = {
  render: () => (
    <div className="w-[28rem] border rounded-16">
      <Card.Header
        headerPadding="sm"
        children={
          <ContentAction
            sizePreset="main-ui"
            variant="section"
            icon={SvgGlobe}
            title="Google Search"
            description="Web search provider"
            padding="fit"
            rightChildren={
              <Button prominence="tertiary" rightIcon={SvgArrowExchange}>
                Connect
              </Button>
            }
          />
        }
      />
    </div>
  ),
};

export const WithBottomRightSlot: Story = {
  render: () => (
    <div className="w-[28rem] border rounded-16">
      <Card.Header
        headerPadding="sm"
        children={
          <ContentAction
            sizePreset="main-ui"
            variant="section"
            icon={SvgGlobe}
            title="Google Search"
            description="Currently the default provider."
            padding="fit"
            rightChildren={
              <Button
                variant="action"
                prominence="tertiary"
                icon={SvgCheckSquare}
              >
                Current Default
              </Button>
            }
          />
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

export const NoRightAction: Story = {
  render: () => (
    <div className="w-[28rem] border rounded-16">
      <Card.Header
        headerPadding="sm"
        children={
          <ContentAction
            sizePreset="main-ui"
            variant="section"
            icon={SvgGlobe}
            title="Section Header"
            description="No actions on the right."
            padding="fit"
          />
        }
      />
    </div>
  ),
};

export const LongContent: Story = {
  render: () => (
    <div className="w-[28rem] border rounded-16">
      <Card.Header
        headerPadding="sm"
        children={
          <ContentAction
            sizePreset="main-ui"
            variant="section"
            icon={SvgGlobe}
            title="Very Long Provider Name That Should Truncate"
            description="This is a much longer description that tests how the layout handles overflow when the content area needs to shrink."
            padding="fit"
            rightChildren={
              <Button
                variant="action"
                prominence="tertiary"
                icon={SvgCheckSquare}
              >
                Current Default
              </Button>
            }
          />
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
