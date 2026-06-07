import type { Meta, StoryObj } from "@storybook/react";
import ApprovalCard from "@/app/craft/components/approvals/ApprovalCard";
import type { ApprovalAction, ApprovalView } from "@/app/craft/types/approvals";

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

const SLACK_POST_MESSAGE: ApprovalAction = {
  action_type: "slack.messages.write",
  display_name: "Post a message",
  description: "Post a message to a channel or conversation.",
  policy: "ASK",
};

const LINEAR_VIEWER_READ: ApprovalAction = {
  action_type: "linear.viewer.read",
  display_name: "Read the connected user",
  description: "Read the authenticated user's profile (viewer).",
  policy: "ALWAYS",
};

const LINEAR_ISSUE_CREATE: ApprovalAction = {
  action_type: "linear.issues.create",
  display_name: "Create an issue",
  description: "Create a new issue in a Linear team.",
  policy: "ASK",
};

function approval(overrides: Partial<ApprovalView>): ApprovalView {
  const merged = {
    approval_id: "appr-01HX3K9M4Q7W2",
    session_id: "sess-01HX3K9M4Q7W2",
    actions: [SLACK_POST_MESSAGE],
    app_name: "Slack",
    payload: {},
    created_at: "2026-05-28T15:42:11Z",
    decision: null,
    decided_at: null,
    is_live: true,
    ...overrides,
  };
  // The card renders display_payload; mirror payload unless overridden.
  return { display_payload: merged.payload, ...merged };
}

export const Collapsed: Story = {
  args: {
    approval: approval({
      payload: {
        channel: "#eng-craft",
        text: "Heads up — the docfetching worker is restarting in 5min for the new tracing flag rollout.",
      },
    }),
  },
};

export const SlackShortMessage: Story = {
  args: {
    defaultOpen: true,
    approval: approval({
      payload: {
        channel: "#eng-craft",
        text: "Heads up — the docfetching worker is restarting in 5min for the new tracing flag rollout.",
      },
    }),
  },
};

export const SlackLongMessageTruncated: Story = {
  args: {
    defaultOpen: true,
    approval: approval({
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

export const SlackWithAttachments: Story = {
  args: {
    defaultOpen: true,
    approval: approval({
      payload: {
        channel: "#eng-craft",
        attachments: [{ fallback: "Build failed", color: "danger" }],
      },
    }),
  },
};

// Batched GraphQL POST that invoked two operations under one
// approval. The collapsed header collapses to "N actions"; the
// expanded body lists each one with its description.
export const BatchedGraphQLMultiAction: Story = {
  args: {
    defaultOpen: true,
    approval: approval({
      app_name: "Linear",
      actions: [LINEAR_VIEWER_READ, LINEAR_ISSUE_CREATE],
      payload: {
        query:
          "query { viewer { id } }\nmutation { issueCreate(input: $i) { issue { id } } }",
      },
    }),
  },
};
