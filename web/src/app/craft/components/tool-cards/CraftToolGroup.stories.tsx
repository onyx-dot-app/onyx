import type { Meta, StoryObj } from "@storybook/react";
import CraftToolGroup from "@/app/craft/components/tool-cards/CraftToolGroup";
import type { ToolCallState } from "@/app/craft/types/displayTypes";

const meta: Meta<typeof CraftToolGroup> = {
  title: "Apps/Craft/Tool Cards/Craft Tool Group",
  component: CraftToolGroup,
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
type Story = StoryObj<typeof CraftToolGroup>;

function call(
  id: string,
  overrides: Partial<ToolCallState> = {}
): ToolCallState {
  return {
    id,
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

const READ_BUILD_LIST = call("g-read-1", {
  kind: "read",
  toolName: "read",
  title: "Reading",
  description: "src/app/craft/components/BuildMessageList.tsx",
  rawOutput: "// 269 lines",
});

const READ_CHAT_PANEL = call("g-read-2", {
  kind: "read",
  toolName: "read",
  title: "Reading",
  description: "src/app/craft/components/ChatPanel.tsx",
  rawOutput: "// 482 lines",
});

const GREP_TRAILING_SLOT = call("g-grep-1", {
  kind: "search",
  toolName: "grep",
  title: "Searching content",
  description: "trailingAssistantSlot",
  rawOutput:
    "web/src/app/craft/components/BuildMessageList.tsx:34:  trailingAssistantSlot?: React.ReactNode;\nweb/src/app/craft/components/ChatPanel.tsx:411:              trailingAssistantSlot={",
});

const EDIT_API_SERVICES = call("g-edit-1", {
  kind: "edit",
  toolName: "edit",
  title: "Editing",
  description: "src/app/craft/services/apiServices.ts",
  oldContent: "throw new Error(`Failed: ${res.status}`);",
  newContent:
    "const errorData = await res.json().catch(() => ({}));\nthrow new Error(errorData.detail || `Failed: ${res.status}`);",
});

const BASH_LINT = call("g-bash-1", {
  description: "lint",
  command: "bun run lint",
  rawOutput: "Found 0 warnings and 0 errors.",
});

const BASH_TYPECHECK_FAIL = call("g-bash-fail", {
  description: "type check",
  command: "bun run types:check",
  status: "failed",
  rawOutput:
    "src/app/craft/components/approvals/ApprovalCard.tsx(128,17): error TS2322: Type 'Element' is not assignable to type 'string | RichStr | undefined'.",
});

export const AllCompleted: Story = {
  args: {
    toolCalls: [
      READ_BUILD_LIST,
      READ_CHAT_PANEL,
      GREP_TRAILING_SLOT,
      EDIT_API_SERVICES,
      BASH_LINT,
    ],
  },
};

export const WithInProgress: Story = {
  args: {
    toolCalls: [
      READ_BUILD_LIST,
      READ_CHAT_PANEL,
      call("g-bash-running", {
        description: "type check",
        command: "bun run types:check",
        status: "in_progress",
        rawOutput: "$ tsgo --noEmit --project tsconfig.types.json\n",
      }),
    ],
  },
};

export const WithFailure: Story = {
  args: {
    defaultOpen: true,
    toolCalls: [
      EDIT_API_SERVICES,
      BASH_TYPECHECK_FAIL,
      // A subsequent successful retry should not mask the prior failure
      // in the aggregate header.
      BASH_LINT,
    ],
  },
};

export const SingleStep: Story = {
  args: {
    toolCalls: [BASH_LINT],
  },
};

// Finished skill group at rest: thin border, no comet.
export const CompletedSkill: Story = {
  args: {
    defaultOpen: true,
    toolCalls: [
      call("g-skill-done-1", {
        kind: "other",
        toolName: "skill",
        title: "Running skill",
        description: "Post to Slack",
        skillName: "slack",
        status: "completed",
      }),
      call("g-skill-done-curl", {
        kind: "execute",
        toolName: "bash",
        description: "post message",
        command: "curl -X POST https://slack.com/api/chat.postMessage ...",
        skillName: "slack",
        status: "completed",
        rawOutput: '{"ok": true, "ts": "1717436531.001"}',
      }),
    ],
  },
};

// In-flight skill group: comet around the whole block.
export const WithActiveSkill: Story = {
  args: {
    defaultOpen: true,
    toolCalls: [
      call("g-skill-1", {
        kind: "other",
        toolName: "skill",
        title: "Running skill",
        description: "Deep, multi-source research",
        skillName: "deep-research",
        status: "in_progress",
      }),
      call("g-skill-grep", {
        kind: "search",
        toolName: "grep",
        title: "Searching content",
        description: "cloud revenue",
        skillName: "deep-research",
        status: "completed",
        rawOutput: "12 matches across 4 files",
      }),
      call("g-skill-fetch", {
        kind: "other",
        toolName: "websearch",
        title: "Searching the web",
        description: "q3 cloud market share",
        skillName: "deep-research",
        status: "in_progress",
      }),
    ],
  },
};

export const ManyCalls: Story = {
  args: {
    toolCalls: [
      READ_BUILD_LIST,
      READ_CHAT_PANEL,
      GREP_TRAILING_SLOT,
      EDIT_API_SERVICES,
      BASH_LINT,
      call("g-bash-format", {
        description: "format",
        command: "bun run format:check",
        rawOutput: "All matched files use the correct format.",
      }),
      call("g-bash-tests", {
        description: "tests",
        command: "bun test",
        rawOutput: "Ran 142 tests, 142 passed.",
      }),
    ],
  },
};
