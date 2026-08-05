import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import SpendByUserTable from "@/sections/usage/SpendByUserTable";
import UserUsageDetailModal from "@/sections/usage/UserUsageDetailModal";
import type { UsageExportRecord, UsageExportUser } from "@/lib/usage/userUsage";

function mulberry32(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const MODELS = [
  {
    model: "claude-opus-5",
    provider: "anthropic",
    inRate: 0.0015,
    outRate: 0.0075,
  },
  {
    model: "claude-sonnet-5",
    provider: "anthropic",
    inRate: 0.0003,
    outRate: 0.0015,
  },
  { model: "gpt-5.5", provider: "openai", inRate: 0.0002, outRate: 0.001 },
  {
    model: "gpt-5-mini",
    provider: "openai",
    inRate: 0.00003,
    outRate: 0.00015,
  },
];
const FLOWS = ["chat", "craft", "search", "image generation", "summarization"];

const PEOPLE: { email: string; activity: number }[] = [
  { email: "maya.okafor@acme.dev", activity: 9 },
  { email: "arjun.mehta@acme.dev", activity: 6.5 },
  { email: "lena.fischer@acme.dev", activity: 4 },
  { email: "theo.lindqvist@acme.dev", activity: 3.2 },
  { email: "priya.raman@acme.dev", activity: 2.1 },
  { email: "marcus.hall@acme.dev", activity: 1.4 },
  { email: "sofia.almeida@acme.dev", activity: 0.8 },
  { email: "kenji.tanaka@acme.dev", activity: 0.35 },
  { email: "nadia.petrova@acme.dev", activity: 0.2 },
  { email: "omar.haddad@acme.dev", activity: 0.12 },
  { email: "grace.chen@acme.dev", activity: 0.4 },
  { email: "felix.moreau@acme.dev", activity: 0.09 },
];

function buildUsers(): UsageExportUser[] {
  const random = mulberry32(20260804);
  return PEOPLE.map(({ email, activity }) => {
    const records: UsageExportRecord[] = [];
    for (let daysAgo = 27; daysAgo >= 0; daysAgo--) {
      const date = new Date(Date.UTC(2026, 7, 4));
      date.setUTCDate(date.getUTCDate() - daysAgo);
      const day = date.toISOString().slice(0, 10);
      for (const m of MODELS) {
        if (random() > 0.32) continue;
        const flow = FLOWS[Math.floor(random() * FLOWS.length)]!;
        const input = Math.round(activity * (2_000 + random() * 30_000));
        const output = Math.round(activity * (500 + random() * 6_000));
        const cache = Math.round(input * random() * 0.6);
        records.push({
          model: m.model,
          provider: m.provider,
          flow,
          day,
          input_tokens: input,
          output_tokens: output,
          cache_read_tokens: cache,
          cost_cents: input * m.inRate + output * m.outRate,
        });
      }
    }
    const totals = records.reduce(
      (sum, record) => ({
        input_tokens: sum.input_tokens + record.input_tokens,
        output_tokens: sum.output_tokens + record.output_tokens,
        cache_read_tokens: sum.cache_read_tokens + record.cache_read_tokens,
        cost_cents: sum.cost_cents + record.cost_cents,
      }),
      { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cost_cents: 0 }
    );
    return { email, totals, records };
  });
}

const USERS = buildUsers();
const PERIOD_LABEL = "Jul 5 – Aug 4, 2026";

const meta: Meta<typeof SpendByUserTable> = {
  title: "sections/usage/SpendByUser",
  component: SpendByUserTable,
  parameters: { layout: "padded" },
  decorators: [
    (Story) => (
      <div className="mx-auto max-w-[980px] bg-background-neutral-00 p-6">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof SpendByUserTable>;

function FullFlowDemo() {
  const [selected, setSelected] = useState<string | null>(null);
  const user = USERS.find((candidate) => candidate.email === selected) ?? null;

  return (
    <>
      <SpendByUserTable users={USERS} onSelectUser={setSelected} />
      {user && (
        <UserUsageDetailModal
          user={user}
          periodLabel={PERIOD_LABEL}
          onOpenChange={(open) => {
            if (!open) setSelected(null);
          }}
        />
      )}
    </>
  );
}

export const FullFlow: Story = {
  render: () => <FullFlowDemo />,
};

export const TableOnly: Story = {
  render: () => <SpendByUserTable users={USERS} onSelectUser={() => {}} />,
};

export const DetailModal: Story = {
  render: () => (
    <UserUsageDetailModal
      user={USERS[0]!}
      periodLabel={PERIOD_LABEL}
      onOpenChange={() => {}}
    />
  ),
};

/** Two-day range: checks the daily-spend chart no longer renders giant slabs. */
function shortRangeUser(): UsageExportUser {
  const base = USERS[1]!;
  const days = ["2026-08-02", "2026-08-03"];
  const records = (base.records ?? []).filter((_, index) => index < 12);
  const shortRecords = records.map((record, index) => ({
    ...record,
    day: days[index % days.length]!,
  }));
  const totals = shortRecords.reduce(
    (sum, record) => ({
      input_tokens: sum.input_tokens + record.input_tokens,
      output_tokens: sum.output_tokens + record.output_tokens,
      cache_read_tokens: sum.cache_read_tokens + record.cache_read_tokens,
      cost_cents: sum.cost_cents + record.cost_cents,
    }),
    { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cost_cents: 0 }
  );
  return { email: base.email, totals, records: shortRecords };
}

export const DetailModalShortRange: Story = {
  render: () => (
    <UserUsageDetailModal
      user={shortRangeUser()}
      periodLabel="Aug 2, 2026 – Aug 3, 2026"
      onOpenChange={() => {}}
    />
  ),
};

export const Empty: Story = {
  render: () => <SpendByUserTable users={[]} onSelectUser={() => {}} />,
};
