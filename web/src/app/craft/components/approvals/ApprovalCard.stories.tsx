import type { Meta, StoryObj } from "@storybook/react";
import ApprovalCard from "@/app/craft/components/approvals/ApprovalCard";
import type { ApprovalView } from "@/app/craft/types/approvals";

const meta: Meta<typeof ApprovalCard> = {
  title: "Apps/Craft/Approvals/Approval Card",
  component: ApprovalCard,
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
type Story = StoryObj<typeof ApprovalCard>;

function approval(overrides: Partial<ApprovalView>): ApprovalView {
  return {
    approval_id: "appr-01HX3K9M4Q7W2",
    session_id: "sess-01HX3K9M4Q7W2",
    action_type: "slack.send_message",
    payload: {},
    created_at: "2026-05-28T15:42:11Z",
    decision: null,
    decided_at: null,
    is_live: true,
    ...overrides,
  };
}

// ──────────────────────────────────────────────────────────────────────────
// Collapsed — the real-world default. Single header row: shield icon,
// label, chevron, and the Approve / Reject buttons inline. The user can
// decide without expanding; the payload is one click away when they
// want to verify.
// ──────────────────────────────────────────────────────────────────────────

export const Collapsed: Story = {
  args: {
    approval: approval({
      action_type: "slack.send_message",
      payload: {
        channel: "#eng-craft",
        text: "Heads up — the docfetching worker is restarting in 5min for the new tracing flag rollout.",
      },
    }),
  },
};

// ──────────────────────────────────────────────────────────────────────────
// Expanded states. Each story passes defaultOpen so the body is
// visible without a click. These pin the card-level chrome (header,
// border, buttons + auto-rendered payload inset); the payload variants
// themselves are covered in PayloadView's own stories.
// ──────────────────────────────────────────────────────────────────────────

// Short string values fit inline in the payload's value column.
export const SlackShortMessage: Story = {
  args: {
    defaultOpen: true,
    approval: approval({
      action_type: "slack.send_message",
      payload: {
        channel: "#eng-craft",
        text: "Heads up — the docfetching worker is restarting in 5min for the new tracing flag rollout.",
      },
    }),
  },
};

// Long string values trigger the Show more / Show less toggle on
// their row.
export const SlackLongMessageTruncated: Story = {
  args: {
    defaultOpen: true,
    approval: approval({
      action_type: "slack.send_message",
      payload: {
        channel: "#customer-acme-corp",
        text:
          "Hi team — wanted to flag that the connector backfill we kicked off last night completed " +
          "successfully across all 3 spaces. We re-indexed ~412k documents and ran a sample audit " +
          "against the previous index to confirm chunk parity (99.7% overlap, the gap is from the " +
          "new sentence-splitter heuristic that handles inline code blocks differently). The next " +
          "step is to swap traffic over once the embedding model deploy lands tomorrow morning.",
      },
    }),
  },
};

// Mixed-type payload: an array of objects value falls through to
// pretty-printed JSON in its row's value column.
export const SlackWithAttachments: Story = {
  args: {
    defaultOpen: true,
    approval: approval({
      action_type: "slack.send_message",
      payload: {
        channel: "#eng-craft",
        attachments: [{ fallback: "Build failed", color: "danger" }],
      },
    }),
  },
};

// New integration where the action_type isn't in actionLabels yet —
// the header label falls back to the raw action_type string. The
// payload still renders structurally; no per-integration FE work was
// needed.
export const UnknownActionTypeLabel: Story = {
  args: {
    defaultOpen: true,
    approval: approval({
      action_type: "linear.create_issue",
      payload: {
        team_id: "ENG",
        title: "Investigate connector retry backoff",
        description: "Customer reported gaps after rate-limit storms.",
        priority: 2,
        labels: ["bug", "reliability"],
      },
    }),
  },
};
