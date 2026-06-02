import type { Meta, StoryObj } from "@storybook/react";
import DiffBody from "@/app/craft/components/tool-cards/DiffBody";
import type { ToolCallState } from "@/app/craft/types/displayTypes";

const meta: Meta<typeof DiffBody> = {
  title: "Apps/Craft/Tool Cards/Diff Body",
  component: DiffBody,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <div className="w-[720px]">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof DiffBody>;

function edit(overrides: Partial<ToolCallState>): ToolCallState {
  return {
    id: "edit-1",
    kind: "edit",
    toolName: "edit",
    title: "Editing",
    description: "",
    command: "",
    status: "completed",
    rawOutput: "",
    ...overrides,
  };
}

export const SmallEdit: Story = {
  args: {
    toolCall: edit({
      description: "src/app/craft/services/apiServices.ts",
      oldContent: `if (!res.ok) {
  throw new Error(\`Failed to post approval decision: \${res.status}\`);
}
return res.json();`,
      newContent: `if (!res.ok) {
  const errorData = await res.json().catch(() => ({}));
  throw new Error(
    errorData.detail || \`Failed to post approval decision: \${res.status}\`
  );
}
return res.json();`,
    }),
  },
};

// Spans more than 20 changed lines, so DiffBody auto-flips to side-by-side.
export const LargeEditAutoSplitsView: Story = {
  args: {
    toolCall: edit({
      description: "src/app/craft/components/approvals/ApprovalCard.tsx",
      oldContent: `import { useState } from "react";
import { Button, Text } from "@opal/components";

export default function ApprovalCard({ approval }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button onClick={() => setOpen(!open)}>{approval.action_type}</button>
      {open && <pre>{JSON.stringify(approval.payload, null, 2)}</pre>}
      <Button onClick={() => approve(approval.approval_id)}>Approve</Button>
      <Button onClick={() => reject(approval.approval_id)}>Reject</Button>
    </div>
  );
}`,
      newContent: `import { useEffect, useRef, useState } from "react";
import { useSWRConfig } from "swr";
import { Button, Text } from "@opal/components";
import { cn } from "@opal/utils";
import { SvgChevronDown, SvgShield } from "@opal/icons";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";

interface ApprovalCardProps {
  approval: ApprovalView;
}

export default function ApprovalCard({ approval }: ApprovalCardProps) {
  const { mutate } = useSWRConfig();
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isOpen, setIsOpen] = useState(true);

  const mountedRef = useRef(true);
  useEffect(() => {
    return () => {
      mountedRef.current = false;
    };
  }, []);

  return (
    <div className="rounded-08 border border-status-warning-03 bg-status-warning-00">
      {/* ... */}
    </div>
  );
}`,
    }),
  },
};

export const NewFile: Story = {
  args: {
    toolCall: edit({
      toolName: "write",
      title: "Writing",
      description: "src/hooks/useDebounce.ts",
      isNewFile: true,
      oldContent: "",
      newContent: `import { useEffect, useState } from "react";

export function useDebounce<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(t);
  }, [value, delayMs]);
  return debounced;
}`,
    }),
  },
};

export const Empty: Story = {
  args: {
    toolCall: edit({ description: "src/empty.ts" }),
  },
};
