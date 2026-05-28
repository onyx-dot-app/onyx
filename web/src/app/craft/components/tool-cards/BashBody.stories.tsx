import type { Meta, StoryObj } from "@storybook/react";
import BashBody from "@/app/craft/components/tool-cards/BashBody";
import type { ToolCallState } from "@/app/craft/types/displayTypes";

const meta: Meta<typeof BashBody> = {
  title: "Apps/Craft/Tool Cards/Bash Body",
  component: BashBody,
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
type Story = StoryObj<typeof BashBody>;

function bash(overrides: Partial<ToolCallState>): ToolCallState {
  return {
    id: "bash-1",
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

export const SimpleOutput: Story = {
  args: {
    toolCall: bash({
      description: "list files",
      command: "ls -lah",
      rawOutput: `total 96
drwxr-xr-x  12 wenxi  staff   384 May 28 10:31 .
drwxr-xr-x  31 wenxi  staff   992 May 28 09:54 ..
-rw-r--r--   1 wenxi  staff  4128 May 28 10:30 README.md
drwxr-xr-x   8 wenxi  staff   256 May 28 10:20 src
-rw-r--r--   1 wenxi  staff  1024 May 28 09:54 package.json
-rw-r--r--   1 wenxi  staff   512 May 28 09:54 tsconfig.json`,
    }),
  },
};

export const Streaming: Story = {
  args: {
    toolCall: bash({
      description: "install deps",
      command: "bun install",
      status: "in_progress",
      rawOutput: `bun install v1.3.13
 + react@18.3.1
 + react-dom@18.3.1
 + next@15.0.3
 + swr@2.3.6
 + @opal/components@workspace:lib/opal
 + tailwindcss@4.3.0
`,
    }),
  },
};

export const Failed: Story = {
  args: {
    toolCall: bash({
      description: "type check",
      command: "tsc --noEmit",
      status: "failed",
      rawOutput: `src/app/craft/components/tool-cards/CraftToolCard.tsx:62:25 - error TS2322:
  Type 'ToolCallStatus' is not assignable to type '"pending" | "in_progress" | "completed"'.

  62   const expandable = hasBodyContent(toolCall);
                             ~~~~~~~~~~~~~~~

Found 1 error in src/app/craft/components/tool-cards/CraftToolCard.tsx`,
    }),
  },
};

export const Empty: Story = {
  args: { toolCall: bash({ description: "noop", command: "", rawOutput: "" }) },
};

export const LongOutput: Story = {
  args: {
    toolCall: bash({
      description: "show last 50 git commits",
      command: "git log --oneline -50",
      rawOutput: Array.from(
        { length: 50 },
        (_, i) =>
          `${(0x9b451c4a98 + i).toString(16).slice(0, 10)} feat(craft): change ${i + 1} of 50`
      ).join("\n"),
    }),
  },
};
