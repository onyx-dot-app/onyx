import type { Meta, StoryObj } from "@storybook/react";
import GenericBody from "@/app/craft/components/tool-cards/GenericBody";
import type { ToolCallState } from "@/app/craft/types/displayTypes";

const meta: Meta<typeof GenericBody> = {
  title: "Apps/Craft/Tool Cards/Generic Body",
  component: GenericBody,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <div className="w-[640px]">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof GenericBody>;

function generic(overrides: Partial<ToolCallState>): ToolCallState {
  return {
    id: "generic-1",
    kind: "other",
    toolName: "unknown",
    title: "Running tool",
    description: "",
    command: "",
    status: "completed",
    rawOutput: "",
    ...overrides,
  };
}

export const UnknownToolOutput: Story = {
  args: {
    toolCall: generic({
      description: "session.snapshot",
      rawOutput: `Captured snapshot at 2026-05-28T17:31:04Z
  sessions:    1 active, 0 archived
  artifacts:   17 (3 since last snapshot)
  storage:     412 MB / 2 GB
  warnings:    0`,
    }),
  },
};

export const StructuredJsonHint: Story = {
  args: {
    toolCall: generic({
      description: "skills.list",
      rawOutput: `{
  "skills": [
    { "name": "code-review", "version": "1.2.0" },
    { "name": "playwright",  "version": "0.4.3" },
    { "name": "onyx-cli",    "version": "0.1.0" }
  ]
}`,
    }),
  },
};

export const Empty: Story = {
  args: { toolCall: generic({ description: "noop" }) },
};
