import type { Meta, StoryObj } from "@storybook/react";
import { FieldMessage } from "./FieldMessage";

const meta: Meta<typeof FieldMessage> = {
  title: "refresh-components/messages/FieldMessage",
  component: FieldMessage,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof FieldMessage>;

export const Error: Story = {
  args: {
    variant: "error",
    children: (
      <FieldMessage.Content>This field is required.</FieldMessage.Content>
    ),
  },
};

export const Success: Story = {
  args: {
    variant: "success",
    children: (
      <FieldMessage.Content>Username is available!</FieldMessage.Content>
    ),
  },
};

export const Warning: Story = {
  args: {
    variant: "warning",
    children: (
      <FieldMessage.Content>This action cannot be undone.</FieldMessage.Content>
    ),
  },
};

export const Loading: Story = {
  args: {
    variant: "loading",
    children: (
      <FieldMessage.Content>Checking availability...</FieldMessage.Content>
    ),
  },
};

export const Info: Story = {
  args: {
    variant: "info",
    children: (
      <FieldMessage.Content>
        Passwords must be at least 8 characters.
      </FieldMessage.Content>
    ),
  },
};

export const Idle: Story = {
  args: {
    variant: "idle",
    children: (
      <FieldMessage.Content>Enter your email address.</FieldMessage.Content>
    ),
  },
};

export const AllVariants: Story = {
  name: "All Variants",
  render: () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <FieldMessage variant="error">
        <FieldMessage.Content>Error message</FieldMessage.Content>
      </FieldMessage>
      <FieldMessage variant="success">
        <FieldMessage.Content>Success message</FieldMessage.Content>
      </FieldMessage>
      <FieldMessage variant="warning">
        <FieldMessage.Content>Warning message</FieldMessage.Content>
      </FieldMessage>
      <FieldMessage variant="loading">
        <FieldMessage.Content>Loading message</FieldMessage.Content>
      </FieldMessage>
      <FieldMessage variant="info">
        <FieldMessage.Content>Info message</FieldMessage.Content>
      </FieldMessage>
      <FieldMessage variant="idle">
        <FieldMessage.Content>Idle message</FieldMessage.Content>
      </FieldMessage>
    </div>
  ),
};
