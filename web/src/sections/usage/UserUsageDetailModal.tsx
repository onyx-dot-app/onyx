"use client";

import { useMemo } from "react";
import { Button, Modal, ProgressBar, Text, Tooltip } from "@opal/components";
import { Section } from "@opal/layouts";
import type { IconFunctionComponent } from "@opal/types";
import { formatCalendarDay } from "@/lib/dateUtils";
import { getModelIcon } from "@/lib/languageModels";
import type { UsageExportUser } from "@/lib/usage/userUsage";
import { formatCost, formatTokens } from "@/lib/utils";

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
  for (const record of user.records) {
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
  for (const record of user.records) {
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
  getIcon?: (slice: BreakdownSlice) => IconFunctionComponent;
}

function BreakdownList({
  title,
  slices,
  totalCostCents,
  getIcon,
}: BreakdownListProps) {
  if (slices.length === 0) return null;
  return (
    <Section
      flexDirection="column"
      justifyContent="start"
      alignItems="stretch"
      gap={2}
      width="full"
      height="fit"
    >
      <Text font="main-ui-action" color="text-04">
        {title}
      </Text>
      <Section
        flexDirection="column"
        justifyContent="start"
        alignItems="stretch"
        gap={2.5}
        width="full"
        height="fit"
      >
        {slices.map((slice) => {
          const share =
            totalCostCents > 0 ? slice.cost_cents / totalCostCents : 0;
          const Icon = getIcon?.(slice);
          return (
            <Section
              key={slice.label}
              flexDirection="column"
              justifyContent="start"
              alignItems="stretch"
              gap={1}
              width="full"
              height="fit"
            >
              {/* items-baseline has no Section equivalent, kept as a raw div */}
              <div className="flex items-baseline justify-between gap-3">
                <span className="flex min-w-0 items-center gap-1.5">
                  {Icon && <Icon size={16} className="shrink-0" />}
                  <span className="min-w-0 truncate">
                    <Text font="main-ui-body" color="text-05" nowrap>
                      {slice.label}
                    </Text>
                  </span>
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
            </Section>
          );
        })}
      </Section>
    </Section>
  );
}

function DailySpendStrip({ days }: { days: DailySpend[] }) {
  const max = Math.max(...days.map((day) => day.cost_cents));
  if (days.length < 2 || max <= 0 || days.length > MAX_DAILY_COLUMNS) {
    return null;
  }
  return (
    <Section
      flexDirection="column"
      justifyContent="start"
      alignItems="stretch"
      gap={1}
      width="full"
      height="fit"
    >
      <Text font="main-ui-action" color="text-04">
        Daily spend
      </Text>
      <Section
        role="img"
        aria-label={`Daily spend for the selected period: ${days
          .map(
            (day) =>
              `${formatCalendarDay(day.day)}, ${formatCost(day.cost_cents)}`
          )
          .join("; ")}`}
        flexDirection="row"
        justifyContent="start"
        alignItems="end"
        gap={0.5}
        width="full"
        height={3.5}
      >
        {days.map((day) => (
          <Tooltip
            key={day.day}
            tooltip={`${formatCalendarDay(day.day)} · ${formatCost(day.cost_cents)}`}
            side="top"
            delayDuration={0}
          >
            {/* Full-height hit target so quiet days are hoverable too; flex-1 participates in the parent Section's own layout so it stays a raw div. */}
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
      </Section>
      <Section
        flexDirection="row"
        justifyContent="between"
        alignItems="stretch"
        gap={0}
        width="full"
        height="fit"
      >
        <Text font="secondary-body" color="text-03">
          {formatCalendarDay(days[0]!.day)}
        </Text>
        <Text font="secondary-body" color="text-03">
          {formatCalendarDay(days[days.length - 1]!.day)}
        </Text>
      </Section>
    </Section>
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
      user ? sliceBy(user, (record) => record.flow || UNLABELED_FLOW) : [],
    [user]
  );
  const byProvider = useMemo(
    () =>
      user ? sliceBy(user, (record) => record.provider || UNLABELED_FLOW) : [],
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
          <Section alignItems="stretch" height="auto" gap={6}>
            <div className="flex flex-wrap gap-2">
              <div className="basis-1/2 sm:basis-1/4">
                <StatCell label="Spend" value={formatCost(totals.cost_cents)} />
              </div>
              <div className="basis-1/2 sm:basis-1/4">
                <StatCell
                  label="Input tokens"
                  value={formatTokens(totals.input_tokens)}
                />
              </div>
              <div className="basis-1/2 sm:basis-1/4">
                <StatCell
                  label="Output tokens"
                  value={formatTokens(totals.output_tokens)}
                />
              </div>
              <div className="basis-1/2 sm:basis-1/4">
                <StatCell
                  label="Cache reads"
                  value={formatTokens(totals.cache_read_tokens)}
                />
              </div>
            </div>

            <DailySpendStrip days={days} />
            <BreakdownList
              title="By model"
              slices={byModel}
              totalCostCents={totals.cost_cents}
              getIcon={(slice) => getModelIcon("", slice.label)}
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
              getIcon={(slice) => getModelIcon(slice.label)}
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
