import type { Meta, StoryObj } from "@storybook/react";
import { useEffect, useState } from "react";
import { Button } from "@opal/components";
import CometEdge from "@/app/craft/components/CometEdge";
import CraftToolCard from "@/app/craft/components/tool-cards/CraftToolCard";
import ApprovalCard from "@/app/craft/components/approvals/ApprovalCard";
import type { ToolCallState } from "@/app/craft/types/displayTypes";
import type { ApprovalView } from "@/app/craft/types/approvals";

const meta: Meta<typeof CometEdge> = {
  title: "Apps/Craft/Comet Edge",
  component: CometEdge,
  tags: ["autodocs"],
  argTypes: {
    tone: { control: "select", options: ["info", "success", "error"] },
    speedSeconds: { control: { type: "range", min: 1, max: 8, step: 0.2 } },
    radius: { control: { type: "range", min: 0, max: 20, step: 1 } },
    active: { control: "boolean" },
    settled: { control: "boolean" },
  },
  decorators: [
    (Story) => (
      <div className="w-[560px] p-8">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof CometEdge>;

// Completed call: no self-comet, so the only comet is the wrapping CometEdge.
function toolCall(overrides: Partial<ToolCallState>): ToolCallState {
  return {
    id: "tool-1",
    kind: "search",
    toolName: "websearch",
    title: "Searching the web",
    description: "q3 cloud market share",
    command: "",
    status: "completed",
    rawOutput:
      "## Gartner — Cloud market share Q3\nhttps://gartner.com/...\nAWS 31%, Azure 25%, GCP 11%.\n\n## Canalys\nhttps://canalys.com/...\nTotal spend up 21% YoY.",
    ...overrides,
  };
}

const SKILL_CALL = toolCall({
  kind: "other",
  toolName: "skill",
  title: "Running skill",
  description: "Deep, multi-source research",
  skillName: "deep-research",
});

// A real pending approval — ApprovalCard supplies its own comet edge.
const SLACK_APPROVAL: ApprovalView = {
  approval_id: "appr-01HX3K9M4Q7W2",
  session_id: "sess-01HX3K9M4Q7W2",
  actions: [
    {
      action_type: "slack.messages.write",
      display_name: "Post a message",
      description: "Post a message to a channel or conversation.",
      policy: "ASK",
    },
  ],
  app_name: "Slack",
  payload: {
    channel: "#sales-ops",
    text: "Heads up — 3 enterprise deals slipped to Q4 on procurement review. Recovery playbook in thread. 🧵",
  },
  display_payload: {
    channel: "#sales-ops",
    text: "Heads up — 3 enterprise deals slipped to Q4 on procurement review. Recovery playbook in thread. 🧵",
  },
  created_at: "2026-05-28T15:42:11Z",
  decision: null,
  decided_at: null,
  is_live: true,
};

export const Playground: Story = {
  args: {
    active: true,
    settled: false,
    tone: "info",
    speedSeconds: 2.6,
    radius: 8,
  },
  render: (args) => (
    <CometEdge {...args}>
      <CraftToolCard toolCall={SKILL_CALL} />
    </CometEdge>
  ),
};

export const SkillInFlight: Story = {
  args: { active: true, tone: "info", speedSeconds: 2.6 },
  render: (args) => (
    <CometEdge {...args}>
      <CraftToolCard toolCall={SKILL_CALL} />
    </CometEdge>
  ),
};

// Real ApprovalCard — supplies its own comet, so no outer CometEdge.
export const AwaitingApproval: Story = {
  render: () => <ApprovalCard approval={SLACK_APPROVAL} defaultOpen />,
};

// Decided ApprovalCards (seeded via defaultDecision).
export const Approved: Story = {
  render: () => (
    <ApprovalCard
      approval={SLACK_APPROVAL}
      defaultOpen
      defaultDecision="APPROVED"
    />
  ),
};

export const Denied: Story = {
  render: () => (
    <ApprovalCard
      approval={SLACK_APPROVAL}
      defaultOpen
      defaultDecision="REJECTED"
    />
  ),
};

// Click Approve/Reject to watch the settle cross-fade; a fetch stub makes it
// stick, Reset re-mounts a pending card.
export const SettleTransition: Story = {
  render: function SettleTransitionStory() {
    const [instance, setInstance] = useState(0);
    useEffect(() => {
      const realFetch = window.fetch;
      window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.includes("/approvals/") && url.includes("/decision")) {
          return new Response(JSON.stringify({ success: true }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        return realFetch(input, init);
      }) as typeof window.fetch;
      return () => {
        window.fetch = realFetch;
      };
    }, []);
    return (
      <div className="flex flex-col gap-4">
        <ApprovalCard key={instance} approval={SLACK_APPROVAL} defaultOpen />
        <Button
          prominence="tertiary"
          size="sm"
          onClick={() => setInstance((n) => n + 1)}
        >
          Reset
        </Button>
      </div>
    );
  },
};

// Comet speeds side by side on real tool cards, to dial in the live cadence.
export const SpeedComparison: Story = {
  render: () => (
    <div className="flex flex-col gap-5">
      {[
        { speed: 1.6, note: "fast" },
        { speed: 2.6, note: "skill in flight" },
        { speed: 3.6, note: "approval — slow patrol" },
      ].map(({ speed, note }) => (
        <CometEdge key={speed} active tone="info" speedSeconds={speed}>
          <CraftToolCard toolCall={toolCall({ description: note })} />
        </CometEdge>
      ))}
    </div>
  ),
};
