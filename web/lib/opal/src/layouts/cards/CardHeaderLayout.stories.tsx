import type { Meta, StoryObj } from "@storybook/react";
import { Card, ContentAction } from "@opal/layouts";
import { Button } from "@opal/components";
import {
  SvgArrowExchange,
  SvgCheckSquare,
  SvgGlobe,
  SvgSettings,
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
      <Card.Header>
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
      </Card.Header>
    </div>
  ),
};

export const WithCurrentDefault: Story = {
  render: () => (
    <div className="w-[28rem] border rounded-16">
      <Card.Header>
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
      </Card.Header>
    </div>
  ),
};

export const NoRightAction: Story = {
  render: () => (
    <div className="w-[28rem] border rounded-16">
      <Card.Header>
        <ContentAction
          sizePreset="main-ui"
          variant="section"
          icon={SvgGlobe}
          title="Section Header"
          description="No actions on the right."
          padding="fit"
        />
      </Card.Header>
    </div>
  ),
};

export const WithBottomChildren: Story = {
  render: () => (
    <div className="w-[28rem] border rounded-16">
      <Card.Header
        bottomChildren={
          <div className="flex gap-1 px-2 pb-2">
            <Button
              icon={SvgSettings}
              tooltip="Edit"
              prominence="tertiary"
              size="sm"
            />
          </div>
        }
      >
        <ContentAction
          sizePreset="main-ui"
          variant="section"
          icon={SvgGlobe}
          title="MCP Server"
          description="12 tools available"
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
      </Card.Header>
    </div>
  ),
};

export const LongContent: Story = {
  render: () => (
    <div className="w-[28rem] border rounded-16">
      <Card.Header>
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
      </Card.Header>
    </div>
  ),
};
