import type { Meta, StoryObj } from "@storybook/react";
import CraftToolCard from "@/app/craft/components/tool-cards/CraftToolCard";
import type { ToolCallState } from "@/app/craft/types/displayTypes";

const meta: Meta<typeof CraftToolCard> = {
  title: "Apps/Craft/Tool Cards/Craft Tool Card",
  component: CraftToolCard,
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
type Story = StoryObj<typeof CraftToolCard>;

function call(overrides: Partial<ToolCallState>): ToolCallState {
  return {
    id: "tool-1",
    kind: "execute",
    toolName: "bash",
    title: "Running command",
    description: "",
    command: "",
    status: "completed",
    rawOutput: "",
    ...overrides,
  };
}

// ──────────────────────────────────────────────────────────────────────────
// Status × kind matrix — the visually distinct combinations the renderer
// actually has to handle. Spinner statuses, success, failure (auto-opens),
// cancelled.
// ──────────────────────────────────────────────────────────────────────────

export const BashCompleted: Story = {
  args: {
    toolCall: call({
      kind: "execute",
      toolName: "bash",
      description: "list files",
      command: "ls -lah src/",
      rawOutput:
        "total 96\ndrwxr-xr-x  12 wenxi  staff   384 May 28 10:31 .\n-rw-r--r--   1 wenxi  staff  4128 May 28 10:30 README.md",
    }),
  },
};

export const BashInProgress: Story = {
  args: {
    toolCall: call({
      kind: "execute",
      toolName: "bash",
      description: "install deps",
      command: "bun install",
      status: "in_progress",
      rawOutput: "bun install v1.3.13\n + react@18.3.1\n + next@15.0.3\n",
    }),
  },
};

export const BashFailed: Story = {
  args: {
    toolCall: call({
      kind: "execute",
      toolName: "bash",
      description: "type check",
      command: "tsc --noEmit",
      status: "failed",
      rawOutput:
        "src/app/page.tsx:12:9 - error TS2322: Type 'string' is not assignable to type 'number'.\n\nFound 1 error.",
    }),
  },
};

export const BashCancelled: Story = {
  args: {
    toolCall: call({
      kind: "execute",
      toolName: "bash",
      description: "long-running command (user cancelled)",
      command: "rg --files | xargs wc -l",
      status: "cancelled",
      rawOutput: "...partial output before cancel...",
    }),
  },
};

export const SkillScriptInProgress: Story = {
  args: {
    toolCall: call({
      kind: "execute",
      toolName: "bash",
      description: "Fetch Linear issue ENG-123",
      command: "python .opencode/skills/linear/linear_api.py issue ENG-123",
      skillName: "linear",
      status: "in_progress",
    }),
  },
};

export const SkillScriptCompleted: Story = {
  args: {
    toolCall: call({
      kind: "execute",
      toolName: "bash",
      description: "List all Linear projects",
      command:
        "python .opencode/skills/linear/linear_api.py projects --limit 100",
      skillName: "linear",
      rawOutput: '[{"id": "proj_1", "name": "Craft"}]',
    }),
  },
};

export const ReadCompleted: Story = {
  args: {
    toolCall: call({
      kind: "read",
      toolName: "read",
      title: "Reading",
      description: "src/app/craft/types/approvals.ts",
      rawOutput:
        'export type ApprovalDecision = "APPROVED" | "REJECTED" | "EXPIRED";',
    }),
  },
};

export const EditCompleted: Story = {
  args: {
    toolCall: call({
      kind: "edit",
      toolName: "edit",
      title: "Editing",
      description: "src/app/craft/services/apiServices.ts",
      command: "",
      oldContent: "throw new Error(`Failed: ${res.status}`);",
      newContent:
        "const errorData = await res.json().catch(() => ({}));\nthrow new Error(errorData.detail || `Failed: ${res.status}`);",
    }),
  },
};

// Write tool: header shows file path + line count; no expandable body
// (hasBodyContent returns false for "write" in CraftToolCard).
export const WriteHasNoExpandableBody: Story = {
  args: {
    toolCall: call({
      kind: "edit",
      toolName: "write",
      title: "Writing",
      description: "src/hooks/useDebounce.ts (12 lines)",
      isNewFile: true,
      newContent:
        'import { useEffect, useState } from "react";\n\nexport function useDebounce<T>(value: T, delayMs: number): T {\n  // ...\n}',
    }),
  },
};

export const SearchGrep: Story = {
  args: {
    toolCall: call({
      kind: "search",
      toolName: "grep",
      title: "Searching content",
      description: "trailingAssistantSlot",
      rawOutput:
        "web/src/app/craft/components/BuildMessageList.tsx:34:  trailingAssistantSlot?: React.ReactNode;\nweb/src/app/craft/components/ChatPanel.tsx:411:              trailingAssistantSlot={",
    }),
  },
};

export const TaskInProgress: Story = {
  args: {
    toolCall: call({
      kind: "task",
      toolName: "task",
      title: "Running task",
      description: "Map tool-cards prop shapes",
      command:
        "Read every tool-card file in web/src/app/craft/components/tool-cards/ and document each component's prop interface, external dependencies, and 2-3 realistic ToolCallState mocks per body.",
      status: "in_progress",
      subagentType: "explore",
    }),
  },
};

export const TaskCompleted: Story = {
  args: {
    toolCall: call({
      kind: "task",
      toolName: "task",
      title: "Running task",
      description: "Draft rebase plan",
      command:
        "Compare whuang/craft-approvals-3-chat-ui against origin/main and propose a replay strategy.",
      status: "completed",
      subagentType: "plan",
      taskOutput:
        "Recommend reset-and-replay over git rebase: the BuildMessageList rewrite produces a textual conflict with no semantic overlap. Drop branch tip, re-apply onto main's new structure.",
    }),
  },
};

export const WebSearch: Story = {
  args: {
    toolCall: call({
      kind: "other",
      toolName: "websearch",
      title: "Searching the web",
      description: "tailwind v4 wrap-break-word",
      rawOutput: `## Overflow wrap - Tailwind CSS
https://tailwindcss.com/docs/overflow-wrap
Utilities for controlling overflow-wrap.

## Tailwind v4 upgrade guide
https://tailwindcss.com/docs/upgrade-guide
The v4 release renamed several utilities.`,
    }),
  },
};

export const WebFetch: Story = {
  args: {
    toolCall: call({
      kind: "other",
      toolName: "webfetch",
      title: "Fetching",
      description: "https://api.github.com/repos/onyx-dot-app/onyx",
      rawOutput:
        '{\n  "name": "onyx",\n  "full_name": "onyx-dot-app/onyx",\n  "stargazers_count": 12450\n}',
    }),
  },
};

export const WithSkillBadge: Story = {
  args: {
    toolCall: call({
      kind: "other",
      toolName: "skill",
      title: "Running skill",
      description: "Review the current diff for correctness bugs",
      command: "/code-review medium",
      skillName: "code-review",
      rawOutput:
        "Found 2 must-fix and 3 should-consider findings. See full review for details.",
    }),
  },
};

// ──────────────────────────────────────────────────────────────────────────
// Skill invocations — comet while in flight, gone once complete.
// ──────────────────────────────────────────────────────────────────────────

export const SkillInFlight: Story = {
  args: {
    toolCall: call({
      kind: "other",
      toolName: "skill",
      title: "Running skill",
      description: "Deep, multi-source research",
      skillName: "deep-research",
      status: "in_progress",
    }),
  },
};

export const SkillCompleted: Story = {
  args: {
    toolCall: call({
      kind: "other",
      toolName: "skill",
      title: "Running skill",
      description: "Review the current diff for correctness bugs",
      command: "/code-review medium",
      skillName: "code-review",
      status: "completed",
      rawOutput:
        "Found 2 must-fix and 3 should-consider findings. See full review for details.",
    }),
  },
};

// ──────────────────────────────────────────────────────────────────────────
// Behavioral overrides — defaultOpen, dense mode.
// ──────────────────────────────────────────────────────────────────────────

export const DefaultOpen: Story = {
  args: {
    defaultOpen: true,
    toolCall: call({
      kind: "execute",
      toolName: "bash",
      description: "show working tree",
      command: "git status -sb",
      rawOutput:
        "## whuang/craft-components-storybook\n M web/.storybook/main.ts\n M web/.storybook/README.md\n?? web/src/app/craft/components/tool-cards/CraftToolCard.stories.tsx",
    }),
  },
};

export const DenseMode: Story = {
  args: {
    dense: true,
    toolCall: call({
      kind: "execute",
      toolName: "bash",
      description: "format code",
      command: "bun run format",
      rawOutput: "All matched files use the correct format.",
    }),
  },
};
