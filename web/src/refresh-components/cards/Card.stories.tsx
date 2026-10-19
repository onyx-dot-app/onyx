import type { Meta, StoryObj } from "@storybook/react-vite";
import Card from "./Card";
import { Text } from "@opal/components";

const meta: Meta<typeof Card> = {
  title: "refresh-components/cards/Card",
  component: Card,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Card>;

export const Primary: Story = {
  args: {
    variant: "primary",
    children: (
      <>
        <Text as="p" font="main-ui-action" color="text-05">
          Card Title
        </Text>
        <Text as="p" font="secondary-body" color="text-03">
          This is a primary card with some content inside.
        </Text>
      </>
    ),
  },
};

export const Secondary: Story = {
  args: {
    variant: "secondary",
    children: (
      <>
        <Text as="p" font="main-ui-action" color="text-05">
          Secondary Card
        </Text>
        <Text as="p" font="secondary-body" color="text-03">
          Less prominent content or nested cards.
        </Text>
      </>
    ),
  },
};

export const Tertiary: Story = {
  args: {
    variant: "tertiary",
    children: (
      <Text as="p" font="secondary-body" color="text-03">
        Dashed border for placeholder or empty states.
      </Text>
    ),
  },
};

export const Disabled: Story = {
  args: {
    variant: "disabled",
    children: (
      <>
        <Text as="p" font="main-ui-action" color="text-05">
          Disabled Card
        </Text>
        <Text as="p" font="secondary-body" color="text-03">
          This content is unavailable.
        </Text>
      </>
    ),
  },
};

export const Borderless: Story = {
  args: {
    variant: "borderless",
    children: (
      <>
        <Text as="p" font="main-ui-action" color="text-05">
          Borderless Card
        </Text>
        <Text as="p" font="secondary-body" color="text-03">
          No border, solid background.
        </Text>
      </>
    ),
  },
};

export const AllVariants: Story = {
  render: () => (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        maxWidth: 400,
      }}
    >
      <Card variant="primary">
        <Text as="p" font="main-ui-action" color="text-05">
          Primary
        </Text>
        <Text as="p" font="secondary-body" color="text-03">
          Default card style
        </Text>
      </Card>
      <Card variant="secondary">
        <Text as="p" font="main-ui-action" color="text-05">
          Secondary
        </Text>
        <Text as="p" font="secondary-body" color="text-03">
          Transparent background
        </Text>
      </Card>
      <Card variant="tertiary">
        <Text as="p" font="main-ui-action" color="text-05">
          Tertiary
        </Text>
        <Text as="p" font="secondary-body" color="text-03">
          Dashed border
        </Text>
      </Card>
      <Card variant="disabled">
        <Text as="p" font="main-ui-action" color="text-05">
          Disabled
        </Text>
        <Text as="p" font="secondary-body" color="text-03">
          Dimmed / unavailable
        </Text>
      </Card>
      <Card variant="borderless">
        <Text as="p" font="main-ui-action" color="text-05">
          Borderless
        </Text>
        <Text as="p" font="secondary-body" color="text-03">
          No border
        </Text>
      </Card>
    </div>
  ),
};
