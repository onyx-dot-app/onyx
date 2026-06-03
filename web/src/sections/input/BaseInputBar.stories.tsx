import type { Meta, StoryObj } from "@storybook/react";
import { Button } from "@opal/components";
import { SvgPlus } from "@opal/icons";
import BaseInputBar from "@/sections/input/BaseInputBar";

const meta: Meta<typeof BaseInputBar> = {
  title: "Apps/Craft/Input Bar/Base Input Bar",
  component: BaseInputBar,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <div className="w-[640px]">
        <Story />
      </div>
    ),
  ],
  args: {
    onSubmit: (msg) => console.log("submit", msg),
    isRunning: false,
  },
};

export default meta;
type Story = StoryObj<typeof BaseInputBar>;

export const Default: Story = {};

export const WithTopSlot: Story = {
  args: {
    topSlot: (
      <div className="flex gap-1">
        <div className="px-2 py-1 rounded-08 bg-background-neutral-01 border border-border-01 text-sm">
          file.pdf
        </div>
        <div className="px-2 py-1 rounded-08 bg-theme-blue-02 border border-theme-blue-04 text-sm">
          ✦ pptx
        </div>
      </div>
    ),
  },
};

export const WithBottomLeftSlot: Story = {
  args: {
    bottomLeftSlot: (
      <Button icon={SvgPlus} prominence="tertiary" tooltip="Add">
        Add
      </Button>
    ),
  },
};

export const Running: Story = {
  args: {
    isRunning: true,
    onInterrupt: () => console.log("interrupt"),
  },
};

export const Disabled: Story = {
  args: { disabled: true },
};

export const SandboxInitializing: Story = {
  args: { sandboxInitializing: true },
};
