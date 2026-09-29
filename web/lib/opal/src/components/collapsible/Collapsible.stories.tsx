import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { Button, Card, Text } from "@opal/components";
import { Collapsible } from "@opal/components/collapsible/components";
import { SvgListTree } from "@opal/icons";

const meta: Meta<typeof Collapsible> = {
  title: "Components/Collapsible",
  component: Collapsible,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Collapsible>;

function Body() {
  return (
    <Card border="solid" rounding={4} padding={4}>
      <Text font="main-ui-body" color="text-03">
        Folded content. Click the title, the description, or the button.
      </Text>
    </Card>
  );
}

export const Default: Story = {
  args: {
    title: "Authentication Account",
    description:
      "Use a shared service account. Onyx indexes content as this account.",
    defaultOpen: true,
  },
  render: (args) => (
    <Collapsible {...args}>
      <Body />
    </Collapsible>
  ),
};

export const WithRightChildren: Story = {
  args: {
    title: "Authentication Account",
    description:
      "Use a shared service account. Onyx indexes content as this account.",
    defaultOpen: true,
  },
  render: (args) => (
    <Collapsible
      {...args}
      rightChildren={
        <Button icon={SvgListTree} prominence="tertiary">
          2 Saved Accounts
        </Button>
      }
    >
      <Body />
    </Collapsible>
  ),
};

/** Controlled: the parent owns the state. */
export const Controlled: Story = {
  render: function ControlledStory() {
    const [open, setOpen] = useState(false);
    return (
      <Collapsible
        title="Details"
        description="Starts closed; the parent holds the state."
        open={open}
        onOpenChange={setOpen}
      >
        <Body />
      </Collapsible>
    );
  },
};
