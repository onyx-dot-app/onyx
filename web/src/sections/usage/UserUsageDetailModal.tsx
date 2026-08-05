"use client";

import { useMemo } from "react";
import { Button, Modal, ProgressBar, Text, Tooltip } from "@opal/components";
import { Section } from "@opal/layouts";
import type { UsageExportUser } from "@/lib/usage/userUsage";
import { formatCost, formatTokens } from "@/sections/usage/SpendByUserTable";

const MAX_DAILY_COLUMNS = 62;
const UNLABELED_FLOW = "other";

interface BreakdownSlice {
  label: string;
  cost_cents: number;
  tokens: number;
}

function sliceBy(
  user: UsageExportUser,
  key: (record: { model: string; flow?: string; provider?: string }) => string
): BreakdownSlice[] {
  const byLabel = new Map<string, BreakdownSlice>();
  for (const record of user.records ?? []) {
    const label = key(record);
    const slice = byLabel.get(label) ?? {
      label,
      cost_cents: 0,
      tokens: 0,
    };
    slice.cost_cents += record.cost_cents;
    slice.tokens += record.input_tokens + record.output_tokens;
    byLabel.set(label, slice);
  }
  return Array.from(byLabel.values()).sort(
    (a, b) => b.cost_cents - a.cost_cents
  );
}

interface DailySpend {
  day: string;
  cost_cents: number;
}

function dailySpend(user: UsageExportUser): DailySpend[] {
  const byDay = new Map<string, number>();
  for (const record of user.records ?? []) {
    byDay.set(record.day, (byDay.get(record.day) ?? 0) + record.cost_cents);
  }
  const days = Array.from(byDay.keys()).sort();
  if (days.length === 0) return [];
  const filled: DailySpend[] = [];
  const first = days[0]!;
  const last = days[days.length - 1]!;
  const cursor = new Date(`${first}T00:00:00Z`);
  const end = new Date(`${last}T00:00:00Z`);
  while (cursor <= end && filled.length < MAX_DAILY_COLUMNS + 1) {
    const day = cursor.toISOString().slice(0, 10);
    filled.push({ day, cost_cents: byDay.get(day) ?? 0 });
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return filled;
}

function formatDayLabel(day: string): string {
  return new Date(`${day}T00:00:00`).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

function StatCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 px-3 first:pl-0 last:pr-0">
      <Text font="secondary-body" color="text-03" nowrap>
        {label}
      </Text>
      <span className="tabular-nums">
        <Text font="main-content-emphasis" nowrap>
          {value}
        </Text>
      </span>
    </div>
  );
}

interface BreakdownListProps {
  title: string;
  slices: BreakdownSlice[];
  totalCostCents: number;
}

function BreakdownList({ title, slices, totalCostCents }: BreakdownListProps) {
  if (slices.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      <Text font="main-ui-action" color="text-04">
        {title}
      </Text>
      <div className="flex flex-col gap-2.5">
        {slices.map((slice) => {
          const share =
            totalCostCents > 0 ? slice.cost_cents / totalCostCents : 0;
          return (
            <div key={slice.label} className="flex flex-col gap-1">
              <div className="flex items-baseline justify-between gap-3">
                <span className="min-w-0 truncate">
                  <Text font="main-ui-body" color="text-05" nowrap>
                    {slice.label}
                  </Text>
                </span>
                <span className="shrink-0 tabular-nums">
                  <Text font="main-ui-body" color="text-05">
                    {formatCost(slice.cost_cents)}
                  </Text>
                  <Text font="secondary-body" color="text-03">
                    {` · ${(share * 100).toFixed(share >= 0.1 ? 0 : 1)}% · ${formatTokens(slice.tokens)} tokens`}
                  </Text>
                </span>
              </div>
              <ProgressBar
                value={slice.cost_cents}
                max={totalCostCents}
                aria-label={`${slice.label} share of spend`}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DailySpendStrip({ days }: { days: DailySpend[] }) {
  const max = Math.max(...days.map((day) => day.cost_cents));
  if (days.length < 2 || max <= 0 || days.length > MAX_DAILY_COLUMNS) {
    return null;
  }
  return (
    <div className="flex flex-col gap-1">
      <Text font="main-ui-action" color="text-04">
        Daily spend
      </Text>
      <div
        role="img"
        aria-label={`Daily spend for the selected period: ${days
          .map(
            (day) => `${formatDayLabel(day.day)}, ${formatCost(day.cost_cents)}`
          )
          .join("; ")}`}
        className="flex h-14 items-end gap-[2px]"
      >
        {days.map((day) => (
          <Tooltip
            key={day.day}
            tooltip={`${formatDayLabel(day.day)} · ${formatCost(day.cost_cents)}`}
            side="top"
            delayDuration={0}
          >
            {/* Full-height hit target so quiet days are hoverable too. */}
            <div className="flex h-full flex-1 items-end">
              <div
                className="w-full rounded-t-[2px] bg-theme-blue-05"
                style={{
                  height:
                    day.cost_cents > 0
                      ? `${Math.max((day.cost_cents / max) * 100, 4)}%`
                      : "2px",
                  opacity: day.cost_cents > 0 ? 1 : 0.25,
                }}
              />
            </div>
          </Tooltip>
        ))}
      </div>
      <div className="flex justify-between">
        <Text font="secondary-body" color="text-03">
          {formatDayLabel(days[0]!.day)}
        </Text>
        <Text font="secondary-body" color="text-03">
          {formatDayLabel(days[days.length - 1]!.day)}
        </Text>
      </div>
    </div>
  );
}

export interface UserUsageDetailModalProps {
  user: UsageExportUser | null;
  periodLabel?: string;
  onOpenChange: (open: boolean) => void;
}

export default function UserUsageDetailModal({
  user,
  periodLabel,
  onOpenChange,
}: UserUsageDetailModalProps) {
  const byModel = useMemo(
    () => (user ? sliceBy(user, (record) => record.model) : []),
    [user]
  );
  const byFlow = useMemo(
    () =>
      user ? sliceBy(user, (record) => record.flow ?? UNLABELED_FLOW) : [],
    [user]
  );
  const byProvider = useMemo(
    () =>
      user ? sliceBy(user, (record) => record.provider ?? UNLABELED_FLOW) : [],
    [user]
  );
  const days = useMemo(() => (user ? dailySpend(user) : []), [user]);

  if (!user) return null;
  const totals = user.totals;

  return (
    <Modal open onOpenChange={onOpenChange}>
      <Modal.Content width="md" height="fit">
        <Modal.Header
          title={user.email}
          description={periodLabel}
          onClose={() => onOpenChange(false)}
        />
        <Modal.Body>
          <Section alignItems="stretch" height="auto" gap={1.5}>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <StatCell label="Spend" value={formatCost(totals.cost_cents)} />
              <StatCell
                label="Input tokens"
                value={formatTokens(totals.input_tokens)}
              />
              <StatCell
                label="Output tokens"
                value={formatTokens(totals.output_tokens)}
              />
              <StatCell
                label="Cache reads"
                value={formatTokens(totals.cache_read_tokens)}
              />
            </div>

            <DailySpendStrip days={days} />
            <BreakdownList
              title="By model"
              slices={byModel}
              totalCostCents={totals.cost_cents}
            />
            <BreakdownList
              title="By flow"
              slices={byFlow}
              totalCostCents={totals.cost_cents}
            />
            <BreakdownList
              title="By provider"
              slices={byProvider}
              totalCostCents={totals.cost_cents}
            />

            {byModel.length === 0 && (
              <Text font="main-ui-body" color="text-03">
                No per-model records for this period.
              </Text>
            )}
          </Section>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={() => onOpenChange(false)}>
            Done
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
