import type { Meta, StoryObj } from "@storybook/react";
import PayloadView from "@/app/craft/components/approvals/PayloadView";

const meta: Meta<typeof PayloadView> = {
  title: "Apps/Craft/Approvals/Payload View",
  component: PayloadView,
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
type Story = StoryObj<typeof PayloadView>;

// ──────────────────────────────────────────────────────────────────────────
// The structured renderer walks the top-level keys of `payload` and
// renders each as a labelled row, picking a format per value type.
// These stories pin the visual contract for each type the renderer
// understands so adding a new integration on the backend doesn't need
// any matching FE work.
// ──────────────────────────────────────────────────────────────────────────

export const ShortStrings: Story = {
  args: {
    payload: {
      channel: "#eng-craft",
      text: "Heads up — the docfetching worker is restarting in 5min.",
    },
  },
};

// Strings past STRING_TRUNCATE_AT (~300 chars) render with Show more /
// Show less. The toggle only controls its own row; other rows are
// unaffected.
export const LongStringWithShowMore: Story = {
  args: {
    payload: {
      channel: "#customer-acme-corp",
      text:
        "Hi team — wanted to flag that the connector backfill we kicked off last night completed " +
        "successfully across all 3 spaces. We re-indexed ~412k documents and ran a sample audit " +
        "against the previous index to confirm chunk parity (99.7% overlap, the gap is from the " +
        "new sentence-splitter heuristic that handles inline code blocks differently). The next " +
        "step is to swap traffic over once the embedding model deploy lands tomorrow morning.",
    },
  },
};

// Numbers, booleans, and arrays of primitives all flatten to inline
// values in the value column.
export const MixedPrimitives: Story = {
  args: {
    payload: {
      team_id: "ENG",
      title: "Investigate connector retry backoff",
      description:
        "Customer reported gaps after rate-limit storms. Looks related to our retry-budget cap.",
      priority: 2,
      labels: ["bug", "reliability", "customer-reported"],
      assignee_active: true,
    },
  },
};

// Nested objects render as pretty-printed JSON inside the value column.
// The InsetBlock's max-height + scroll handles deep nesting.
export const NestedObject: Story = {
  args: {
    payload: {
      contact_id: "vid:1247-9023-1144",
      properties: {
        company: "Acme Corp",
        lifecycle_stage: "customer",
        plan: "enterprise",
      },
    },
  },
};

// Array of objects falls through to pretty-printed JSON. Each object's
// JSON spans 4 lines (open brace + 2 fields + close brace), so even a
// 2-element array crosses the 8-line truncation threshold and gets a
// Show more / Show less button.
export const ArrayOfObjects: Story = {
  args: {
    payload: {
      issue_id: "ENG-1247",
      labels: [
        { name: "bug", color: "#e11d48" },
        { name: "reliability", color: "#f59e0b" },
      ],
    },
  },
};

// Comma-joined primitives past the string-truncation threshold render
// with Show more, just like long string values do.
export const LongArrayOfPrimitives: Story = {
  args: {
    payload: {
      repository: "onyx-dot-app/onyx",
      issue_number: 12047,
      assignees: Array.from(
        { length: 40 },
        (_, i) => `eng-team-member-${(i + 1).toString().padStart(3, "0")}`
      ),
    },
  },
};

// Deeply populated nested object — the value's pretty-printed JSON is
// dozens of lines, so it renders truncated by default with a Show more
// toggle to reveal the full structure.
export const LargeNestedObject: Story = {
  args: {
    payload: {
      contact_id: "vid:1247-9023-1144",
      properties: Object.fromEntries(
        Array.from({ length: 25 }, (_, i) => [
          `custom_field_${i + 1}`,
          `value-${i + 1}`,
        ])
      ),
    },
  },
};

// Keys under the column cap auto-size to fit the widest one across
// rows — no ellipsis needed.
export const WideKeysAllFit: Story = {
  args: {
    payload: {
      repository: "onyx-dot-app/onyx",
      branch: "whuang/feature",
      head_commit_sha: "8a383f69a1",
      title: "Add structured payload renderer",
    },
  },
};

// A key longer than the 10rem column cap cuts off with a CSS ellipsis.
// Hover the truncated key to see the full string via the native title
// attribute (the same affordance used elsewhere in the app for
// hover-for-full).
export const TruncatedWideKey: Story = {
  args: {
    payload: {
      external_user_reference_id_for_legacy_migration: "usr_abc123",
      lifecycle_stage_at_time_of_record_creation: "qualified_lead",
      plan: "enterprise",
    },
  },
};

// Null / undefined values are filtered out before rendering. An empty
// payload (or one containing only nulls) falls to a "No payload"
// notice rather than an empty inset.
export const EmptyPayload: Story = {
  args: {
    payload: {},
  },
};
