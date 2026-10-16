import type { Meta, StoryObj } from "@storybook/react-vite";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { Collapsible, Text } from "@opal/components";

const meta: Meta<typeof Collapsible> = {
  title: "opal/components/Collapsible",
  component: Collapsible,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <div className="w-[40rem]">
          <Story />
        </div>
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof Collapsible>;

export const Open: Story = {
  args: {
    title: "Schedule",
    description: "Specify how the connector will operate indexing.",
    children: <Text color="text-03">Section body</Text>,
  },
};

export const Folded: Story = {
  args: {
    title: "Schedule",
    description: "Specify how the connector will operate indexing.",
    defaultOpen: false,
    children: <Text color="text-03">Section body</Text>,
  },
};
