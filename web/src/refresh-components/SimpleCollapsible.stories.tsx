import type { Meta, StoryObj } from "@storybook/react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import SimpleCollapsible from "./SimpleCollapsible";

const meta: Meta<typeof SimpleCollapsible> = {
  title: "refresh-components/SimpleCollapsible",
  component: SimpleCollapsible,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <Story />
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof SimpleCollapsible>;

export const DefaultOpen: Story = {
  render: () => (
    <SimpleCollapsible>
      <SimpleCollapsible.Header
        title="Section Title"
        description="This section is open by default."
      />
      <SimpleCollapsible.Content>
        <div>Here is some collapsible content that starts expanded.</div>
      </SimpleCollapsible.Content>
    </SimpleCollapsible>
  ),
};

export const DefaultClosed: Story = {
  render: () => (
    <SimpleCollapsible defaultOpen={false}>
      <SimpleCollapsible.Header
        title="Initially Closed"
        description="Click the button to expand this section."
      />
      <SimpleCollapsible.Content>
        <div>This content was hidden until you clicked expand.</div>
      </SimpleCollapsible.Content>
    </SimpleCollapsible>
  ),
};

export const TitleOnly: Story = {
  render: () => (
    <SimpleCollapsible>
      <SimpleCollapsible.Header title="No Description" />
      <SimpleCollapsible.Content>
        <div>Content with a header that has no description.</div>
      </SimpleCollapsible.Content>
    </SimpleCollapsible>
  ),
};
