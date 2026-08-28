"use client";

import React, { useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
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
  const t = useTranslations("admin.perUserUsage");
  const locale = useLocale();
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
      <Text font="heading-h3">{t("panel.title")}</Text>
      <Text font="secondary-body" color="text-03">
        {usage
          ? t("panel.description", {
              start: formatDate(usage.start),
              end: formatDate(usage.end),
            })
          : t("panel.emptyDescription")}
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
          title={t("panel.error.title")}
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

      <Card border="solid" rounding={4} padding={0}>
        <div className="grid grid-cols-2 lg:grid-cols-4">
          <div className="border-b border-border-02 lg:border-b-0">
            <SummaryMetric
              label={t("summary.workspaceSpend.label")}
              value={formatCost(totalCostCents, locale)}
              detail={t("summary.workspaceSpend.detail")}
            />
          </div>
          <div className="border-b border-l border-border-02 lg:border-b-0">
            <SummaryMetric
              label={t("summary.totalTokens.label")}
              value={formatTokens(totalTokens, locale)}
              detail={t("summary.totalTokens.detail")}
            />
          </div>
          <div className="border-b border-border-02 lg:border-b-0 lg:border-l">
            <SummaryMetric
              label={t("summary.activeUsers.label")}
              value={formatTokens(activeUsers, locale)}
              detail={t("summary.activeUsers.detail", { count: users.length })}
            />
          </div>
          <div className="border-l border-border-02">
            <SummaryMetric
              label={t("summary.topSpender.label")}
              value={
                topSpender
                  ? formatCost(topSpender.totals.cost_cents, locale)
                  : "—"
              }
              detail={topSpender?.email ?? t("summary.topSpender.noSpend")}
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
          <Text font="heading-h3">{t("users.title")}</Text>
          <Text font="secondary-body" color="text-03">
            {t("users.description")}
          </Text>
        </Section>

        {users.length === 0 ? (
          <Card border="solid" rounding={4} padding={3}>
            <Text font="main-ui-body" color="text-03">
              {t("users.empty.description")}
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
