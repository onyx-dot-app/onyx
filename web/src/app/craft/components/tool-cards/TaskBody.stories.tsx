import type { Meta, StoryObj } from "@storybook/react";
import TaskBody from "@/app/craft/components/tool-cards/TaskBody";
import type { ToolCallState } from "@/app/craft/types/displayTypes";

const meta: Meta<typeof TaskBody> = {
  title: "Apps/Craft/Tool Cards/Task Body",
  component: TaskBody,
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
type Story = StoryObj<typeof TaskBody>;

function task(overrides: Partial<ToolCallState>): ToolCallState {
  return {
    id: "task-1",
    kind: "task",
    toolName: "task",
    title: "Running task",
    description: "",
    command: "",
    status: "completed",
    rawOutput: "",
    ...overrides,
  };
}

export const InProgressExplore: Story = {
  args: {
    toolCall: task({
      description: "Map tool-cards prop shapes",
      command:
        "Read every tool-card file in web/src/app/craft/components/tool-cards/ and document each component's prop interface, external dependencies, and 2-3 realistic ToolCallState mocks per body.",
      status: "in_progress",
      subagentType: "explore",
    }),
  },
};

export const CompletedWithOutput: Story = {
  args: {
    toolCall: task({
      description: "Draft rebase plan",
      command:
        "Compare whuang/craft-approvals-3-chat-ui against origin/main. Identify all conflicts in BuildMessageList.tsx and ChatPanel.tsx given main's tool-cards refactor. Propose a reset-and-replay strategy.",
      status: "completed",
      subagentType: "plan",
      taskOutput: `Plan: reset whuang/craft-approvals-3-chat-ui to origin/main, then re-apply the approvals UI cleanly on top of main's new BuildMessageList structure.

Steps:
1. git reset --hard origin/main
2. Add types/approvals.ts, hooks/useLiveApprovals.ts, components/approvals/* (clean adds)
3. Append fetchLiveApprovals + postApprovalDecision + ApprovalConflictError to apiServices.ts
4. Re-implement trailingAssistantSlot in main's BuildMessageList.tsx
5. Wire LiveApprovalsRegion into ChatPanel.tsx on main's structure
6. Re-apply backend K8S_CONTEXT env support to k8s_client.py + env template
7. Type-check + lint, commit as single feat

Why reset instead of git rebase: the BuildMessageList rewrite produces a textual conflict block where the surrounding code on each side is unrelated. Replaying onto the new structure is faster and produces a cleaner diff for review.`,
    }),
  },
};

export const FailedNoOutput: Story = {
  args: {
    toolCall: task({
      description: "Audit external API surface",
      command:
        "Inventory every endpoint exposed under /api/build/ and classify by auth requirements.",
      status: "failed",
      subagentType: "explore",
      rawOutput: "subagent exited without producing output",
    }),
  },
};

export const PromptOnly: Story = {
  args: {
    toolCall: task({
      description: "Investigate flaky test",
      command:
        "Tests in web/tests/e2e/craft/approvals.spec.ts intermittently fail with 'timeout waiting for selector [data-testid=live-approvals-region]'. Determine root cause.",
      status: "in_progress",
      subagentType: "explore",
    }),
  },
};
