import type { Meta, StoryObj } from "@storybook/react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import Code from "./Code";

const meta: Meta<typeof Code> = {
  title: "refresh-components/Code",
  component: Code,
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
type Story = StoryObj<typeof Code>;

export const Default: Story = {
  args: {
    children: `const greeting = "Hello, world!";\nconsole.log(greeting);`,
  },
};

export const WithoutCopyButton: Story = {
  args: {
    children: `npm install @onyx/sdk`,
    showCopyButton: false,
  },
};

export const MultiLine: Story = {
  args: {
    children: `function fibonacci(n: number): number {
  if (n <= 1) return n;
  return fibonacci(n - 1) + fibonacci(n - 2);
}

console.log(fibonacci(10));`,
  },
};
