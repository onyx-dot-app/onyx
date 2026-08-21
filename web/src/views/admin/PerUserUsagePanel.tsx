"use client";

import React, { useMemo, useState } from "react";
import { Card, MessageCard, Text } from "@opal/components";
import { SvgX } from "@opal/icons";
import { PageLoader, Section } from "@opal/layouts";
import type { DateRange } from "@/refresh-components/DateRangePicker";
import { formatCalendarDay } from "@/lib/dateUtils";
import { useUsageExport } from "@/lib/usage/userUsage";
import { formatCost, formatTokens } from "@/lib/utils";
import SpendByUserTable from "@/sections/usage/SpendByUserTable";
import UserUsageDetailModal from "@/sections/usage/UserUsageDetailModal";

function formatDate(value: string): string {
  return formatCalendarDay(value, { withYear: true });
}

function SummaryMetric({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 px-3 py-3 sm:px-4">
      <Text font="secondary-body" color="text-03">
        {label}
      </Text>
      <span className="tabular-nums">
        <Text font="heading-h3">{value}</Text>
      </span>
      <span className="block min-w-0 truncate" title={detail}>
        <Text font="secondary-body" color="text-03">
          {detail}
        </Text>
      </span>
    </div>
  );
}

interface PerUserUsagePanelProps {
  timeRange?: DateRange;
}

export default function PerUserUsagePanel({
  timeRange,
}: PerUserUsagePanelProps) {
  const { usage, isLoading, error } = useUsageExport(timeRange);
  const [selectedEmail, setSelectedEmail] = useState<string | null>(null);

  const users = usage?.users ?? [];
  const selectedUser =
    users.find((user) => user.email === selectedEmail) ?? null;

  const totalCostCents = useMemo(
    () => users.reduce((total, user) => total + user.totals.cost_cents, 0),
    [users]
  );
  const totalTokens = useMemo(
    () =>
      users.reduce(
        (total, user) =>
          total + user.totals.input_tokens + user.totals.output_tokens,
        0
      ),
    [users]
  );
  const activeUsers = users.filter(
    (user) =>
      user.totals.input_tokens > 0 ||
      user.totals.output_tokens > 0 ||
      user.totals.cache_read_tokens > 0 ||
      user.totals.cost_cents > 0
  ).length;
  const topSpender = users.reduce<(typeof users)[number] | null>(
    (top, user) =>
      user.totals.cost_cents > 0 &&
      (top === null || user.totals.cost_cents > top.totals.cost_cents)
        ? user
        : top,
    null
  );

  const header = (
    <Section
      flexDirection="column"
      justifyContent="start"
      alignItems="stretch"
      gap={0.125}
      width="full"
      height="fit"
    >
      <Text font="heading-h3">Usage overview</Text>
      <Text font="secondary-body" color="text-03">
        {usage
          ? `${formatDate(usage.start)} – ${formatDate(usage.end)} · Costs are calculated from recorded model usage.`
          : "Per-user spend and token usage for the selected period."}
      </Text>
    </Section>
  );

  if (isLoading) {
    return (
      <Section
        flexDirection="column"
        justifyContent="start"
        alignItems="stretch"
        gap={1}
        width="full"
        height="fit"
      >
        {header}
        <PageLoader />
      </Section>
    );
  }
  if (error) {
    return (
      <Section
        flexDirection="column"
        justifyContent="start"
        alignItems="stretch"
        gap={1}
        width="full"
        height="fit"
      >
        {header}
        <MessageCard
          variant="error"
          icon={SvgX}
          title="Failed to load usage for this period."
        />
      </Section>
    );
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
      {header}

      <Card border="solid" rounding="lg" padding={0}>
        <div className="grid grid-cols-2 lg:grid-cols-4">
          <div className="border-b border-border-02 lg:border-b-0">
            <SummaryMetric
              label="Workspace spend"
              value={formatCost(totalCostCents)}
              detail="Across all listed users"
            />
          </div>
          <div className="border-b border-l border-border-02 lg:border-b-0">
            <SummaryMetric
              label="Total tokens"
              value={formatTokens(totalTokens)}
              detail="Input (including cache reads) and output"
            />
          </div>
          <div className="border-b border-border-02 lg:border-b-0 lg:border-l">
            <SummaryMetric
              label="Active users"
              value={activeUsers.toLocaleString()}
              detail={`${users.length.toLocaleString()} users with records`}
            />
          </div>
          <div className="border-l border-border-02">
            <SummaryMetric
              label="Top spender"
              value={
                topSpender ? formatCost(topSpender.totals.cost_cents) : "—"
              }
              detail={topSpender?.email ?? "No spend recorded"}
            />
          </div>
        </div>
      </Card>

      <Section
        flexDirection="column"
        justifyContent="start"
        alignItems="stretch"
        gap={0.5}
        width="full"
        height="fit"
      >
        <Section
          flexDirection="column"
          justifyContent="start"
          alignItems="stretch"
          gap={0.125}
          width="full"
          height="fit"
        >
          <Text font="heading-h3">Users</Text>
          <Text font="secondary-body" color="text-03">
            Spend is sorted highest first. Filter the list, then select a user
            for a complete breakdown.
          </Text>
        </Section>

        {users.length === 0 ? (
          <Card border="solid" rounding="lg" padding={3}>
            <Text font="main-ui-body" color="text-03">
              No usage recorded for this period.
            </Text>
          </Card>
        ) : (
          <SpendByUserTable users={users} onSelectUser={setSelectedEmail} />
        )}
      </Section>

      {selectedUser && (
        <UserUsageDetailModal
          user={selectedUser}
          periodLabel={
            usage
              ? `${formatDate(usage.start)} – ${formatDate(usage.end)}`
              : undefined
          }
          onOpenChange={(open) => {
            if (!open) setSelectedEmail(null);
          }}
        />
      )}
    </Section>
  );
}
