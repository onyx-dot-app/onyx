import type { Meta, StoryObj } from "@storybook/react";
import ReadBody from "@/app/craft/components/tool-cards/ReadBody";
import type { ToolCallState } from "@/app/craft/types/displayTypes";

const meta: Meta<typeof ReadBody> = {
  title: "Apps/Craft/Tool Cards/Read Body",
  component: ReadBody,
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
type Story = StoryObj<typeof ReadBody>;

function read(overrides: Partial<ToolCallState>): ToolCallState {
  return {
    id: "read-1",
    kind: "read",
    toolName: "read",
    title: "Reading",
    description: "",
    command: "",
    status: "completed",
    rawOutput: "",
    ...overrides,
  };
}

export const TypeScriptShort: Story = {
  args: {
    toolCall: read({
      description: "src/app/craft/types/approvals.ts",
      rawOutput: `export type ApprovalDecision = "APPROVED" | "REJECTED" | "EXPIRED";

export type ApprovalSubmitDecision = "APPROVED" | "REJECTED";

export interface ApprovalView {
  approval_id: string;
  session_id: string;
  action_type: string;
  payload: Record<string, unknown>;
  created_at: string;
  decision: ApprovalDecision | null;
  decided_at: string | null;
  is_live: boolean;
}`,
    }),
  },
};

export const JsonConfig: Story = {
  args: {
    toolCall: read({
      description: "tsconfig.json",
      rawOutput: `{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "noEmit": true,
    "jsx": "preserve",
    "paths": { "@/*": ["./src/*"], "@opal/*": ["./lib/opal/src/*"] }
  },
  "include": ["src", "lib"],
  "exclude": ["node_modules", ".next"]
}`,
    }),
  },
};

export const TruncatesAfterEight: Story = {
  args: {
    toolCall: read({
      description: "src/app/craft/components/BuildMessageList.tsx",
      rawOutput: Array.from(
        { length: 40 },
        (_, i) => `  // line ${i + 1}: render stream item ${i + 1}`
      ).join("\n"),
    }),
  },
};

export const NewFileViaWrite: Story = {
  args: {
    toolCall: read({
      toolName: "write",
      title: "Writing",
      description: "src/hooks/useDebounce.ts",
      isNewFile: true,
      newContent: `import { useEffect, useState } from "react";

export function useDebounce<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(t);
  }, [value, delayMs]);
  return debounced;
}`,
      rawOutput: "",
    }),
  },
};

export const Empty: Story = {
  args: {
    toolCall: read({
      description: "src/index.ts",
      rawOutput: "",
    }),
  },
};
