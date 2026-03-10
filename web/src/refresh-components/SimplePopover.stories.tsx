import type { Meta, StoryObj } from "@storybook/react";
import SimplePopover from "./SimplePopover";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";

const meta: Meta<typeof SimplePopover> = {
  title: "refresh-components/modals/SimplePopover",
  component: SimplePopover,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
};

export default meta;
type Story = StoryObj<typeof SimplePopover>;

export const Default: Story = {
  args: {
    trigger: <Button>Open Popover</Button>,
    children: (
      <div style={{ padding: 16 }}>
        <Text mainUiBody text04>
          Popover content goes here.
        </Text>
      </div>
    ),
  },
};

export const WithRenderPropTrigger: Story = {
  args: {
    trigger: (open: boolean) => (
      <Button>{`${open ? "Close" : "Open"} Popover`}</Button>
    ),
    children: (
      <div style={{ padding: 16 }}>
        <Text mainUiBody text04>
          The trigger updates its label based on open state.
        </Text>
      </div>
    ),
  },
};
