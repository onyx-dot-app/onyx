import type { Meta, StoryObj } from "@storybook/react";
import InlineExternalLink from "./InlineExternalLink";

const meta: Meta<typeof InlineExternalLink> = {
  title: "refresh-components/InlineExternalLink",
  component: InlineExternalLink,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
};

export default meta;
type Story = StoryObj<typeof InlineExternalLink>;

export const Default: Story = {
  args: {
    href: "https://docs.onyx.app",
    children: "Onyx Documentation",
  },
};

export const CustomClassName: Story = {
  args: {
    href: "https://github.com/onyx-dot-app/onyx",
    children: "GitHub Repository",
    className: "text-action-link-05 underline hover:opacity-80",
  },
};

export const InContext: Story = {
  render: () => (
    <p className="font-main-content-body text-text-04">
      For more information, visit the{" "}
      <InlineExternalLink href="https://docs.onyx.app">
        official documentation
      </InlineExternalLink>{" "}
      or check out the{" "}
      <InlineExternalLink href="https://github.com/onyx-dot-app/onyx">
        source code
      </InlineExternalLink>
      .
    </p>
  ),
};
