import type { Meta, StoryObj } from "@storybook/react";
import { EndOfList } from "@opal/components";
import { markdown } from "@opal/utils";

const meta: Meta<typeof EndOfList> = {
  title: "opal/components/EndOfList",
  component: EndOfList,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof EndOfList>;

export const Or: Story = {
  render: () => <EndOfList title="or" />,
};

export const CustomTitle: Story = {
  render: () => <EndOfList title="and then" />,
};

export const MarkdownTitle: Story = {
  render: () => <EndOfList title={markdown("*or* sign in with SSO")} />,
};
