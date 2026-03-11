import type { Meta, StoryObj } from "@storybook/react";
import Message from "./Message";

const meta: Meta<typeof Message> = {
  title: "refresh-components/messages/Message",
  component: Message,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Message>;

export const Default: Story = {
  args: {
    text: "This is a default message.",
  },
};

export const FlashInfo: Story = {
  args: {
    flash: true,
    info: true,
    text: "Your changes have been saved.",
    description: "The settings will take effect immediately.",
  },
};

export const FlashSuccess: Story = {
  args: {
    flash: true,
    success: true,
    text: "Operation completed successfully!",
  },
};

export const FlashWarning: Story = {
  args: {
    flash: true,
    warning: true,
    text: "Your session is about to expire.",
    description: "Please save your work before the session ends.",
  },
};

export const FlashError: Story = {
  args: {
    flash: true,
    error: true,
    text: "Something went wrong.",
    description: "Please try again or contact support.",
  },
};

export const StaticInfo: Story = {
  args: {
    static: true,
    info: true,
    text: "This is informational.",
    description: "Here is some extra context.",
  },
};

export const StaticSuccess: Story = {
  args: {
    static: true,
    success: true,
    text: "All checks passed.",
  },
};

export const StaticWarning: Story = {
  args: {
    static: true,
    warning: true,
    text: "Proceed with caution.",
  },
};

export const StaticError: Story = {
  args: {
    static: true,
    error: true,
    text: "Failed to load resource.",
  },
};

export const MediumSize: Story = {
  args: {
    flash: true,
    info: true,
    medium: true,
    text: "Medium sized message.",
    description: "Compact layout for tight spaces.",
  },
};

export const WithAction: Story = {
  args: {
    flash: true,
    warning: true,
    text: "Unsaved changes detected.",
    actions: "Undo",
    onAction: () => alert("Action clicked"),
  },
};

export const WithoutIcon: Story = {
  args: {
    flash: true,
    info: true,
    icon: false,
    text: "Message without an icon.",
  },
};

export const WithoutCloseButton: Story = {
  args: {
    flash: true,
    success: true,
    close: false,
    text: "This message cannot be dismissed.",
  },
};

export const AllLevels: Story = {
  name: "All Levels (Flash / Large)",
  render: () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Message flash default text="Default flash message" />
      <Message flash info text="Info flash message" />
      <Message flash success text="Success flash message" />
      <Message flash warning text="Warning flash message" />
      <Message flash error text="Error flash message" />
    </div>
  ),
};
