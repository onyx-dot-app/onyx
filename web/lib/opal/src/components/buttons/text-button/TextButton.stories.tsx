import type { Meta, StoryObj } from "@storybook/react";
import { TextButton } from "@opal/components";

const meta: Meta<typeof TextButton> = {
  title: "opal/components/TextButton",
  component: TextButton,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof TextButton>;

export const Default: Story = {
  args: {
    children: "Text button",
  },
};

export const Fonts: Story = {
  render: () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <TextButton font="main-ui-body">main-ui-body (default)</TextButton>
      <TextButton font="main-ui-action">main-ui-action</TextButton>
      <TextButton font="secondary-action">secondary-action</TextButton>
      <TextButton font="heading-h3">heading-h3</TextButton>
    </div>
  ),
};

export const Disabled: Story = {
  args: {
    disabled: true,
    children: "Disabled",
  },
};

export const AsLink: Story = {
  args: {
    href: "https://example.com",
    children: "Visit site",
  },
};

export const InlineInProse: Story = {
  render: () => (
    <p style={{ maxWidth: "36rem", lineHeight: 1.7 }}>
      You can undo this action within the next 30 seconds.{" "}
      <TextButton onClick={() => alert("undone")}>Undo</TextButton>.
    </p>
  ),
};
