import React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import Popover from "./Popover";
import { Button } from "@opal/components";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof Popover> = {
  title: "refresh-components/Popover",
  component: Popover,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <Story />
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof Popover>;

export const Default: Story = {
  render: () => (
    <Popover>
      <Popover.Trigger asChild>
        <Button>Open Popover</Button>
      </Popover.Trigger>
      <Popover.Content>
        <div style={{ padding: 8 }}>
          <p>Popover content goes here.</p>
        </div>
      </Popover.Content>
    </Popover>
  ),
};

export const WidthVariants: Story = {
  render: () => (
    <div style={{ display: "flex", gap: 16 }}>
      {(["fit", "md", "lg", "xl"] as const).map((width) => (
        <Popover key={width}>
          <Popover.Trigger asChild>
            <Button prominence="secondary">{width}</Button>
          </Popover.Trigger>
          <Popover.Content width={width}>
            <div style={{ padding: 8 }}>
              <p>Width: {width}</p>
            </div>
          </Popover.Content>
        </Popover>
      ))}
    </div>
  ),
};

export const WithMenu: Story = {
  render: () => (
    <Popover>
      <Popover.Trigger asChild>
        <Button>Options</Button>
      </Popover.Trigger>
      <Popover.Content width="lg">
        <Popover.Menu>
          <Popover.Close asChild>
            <Button prominence="tertiary" width="full">
              Edit
            </Button>
          </Popover.Close>
          <Popover.Close asChild>
            <Button prominence="tertiary" width="full">
              Duplicate
            </Button>
          </Popover.Close>
          {null}
          <Popover.Close asChild>
            <Button variant="danger" prominence="tertiary" width="full">
              Delete
            </Button>
          </Popover.Close>
        </Popover.Menu>
      </Popover.Content>
    </Popover>
  ),
};
