"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import useSWR from "swr";
import { Card, Dropdown, OpenButton, Tag, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgClock } from "@opal/icons";
import { CardLoader } from "@opal/loaders";
import { timeAgo } from "@opal/time";
import {
  ConnectorCredentialPairStatus,
  type CCPairFullInfo,
  type CCPairThroughputWindow,
  type PaginatedIndexAttempts,
} from "@/lib/connectors/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { ccPairStatusTag } from "@/views/admin/connectors/ConnectorDetailPage/statusTag";
import ThroughputChart from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";

/** The chart's windows. Their labels reuse the run list's time ranges. */
const WINDOW_LABEL_KEYS = {
  "12h": "h12",
  "24h": "h24",
  "7d": "d7",
} as const satisfies Record<CCPairThroughputWindow, string>;
const WINDOWS = Object.keys(WINDOW_LABEL_KEYS) as CCPairThroughputWindow[];

// The chart waits for the pair's first successful run.
const FIRST_RUN_STATUSES = new Set<ConnectorCredentialPairStatus>([
  ConnectorCredentialPairStatus.SCHEDULED,
  ConnectorCredentialPairStatus.INITIAL_INDEXING,
]);

interface StatBlockProps {
  children: React.ReactNode;
}
/** One column of the card: a figure or tag over its two-line label. */
function StatBlock({ children }: StatBlockProps) {
  return (
    // Columns share the row evenly and wrap below 12rem, so three fit at 640px.
    <Section
      alignItems="start"
      justifyContent="start"
      gap={1}
      padding={2}
      width="auto"
      height="fit"
      className="grow basis-0 min-w-48"
    >
      {children}
    </Section>
  );
}

// Matches the page's own poll of the pair.
const POLL_MS = 5000;

export interface StatusCardProps {
  ccPair: CCPairFullInfo;
}

/** The pair at a glance: status, latest and total documents, its last run, and documents indexed over time. */
export default function StatusCard({ ccPair }: StatusCardProps) {
  const t = useTranslations("admin.connector.statusCard");
  const tBadges = useTranslations("admin.status.badges");
  const tWindow = useTranslations("admin.connector.runs.window");
  const locale = useLocale();
  const [range, setRange] = useState<CCPairThroughputWindow>("12h");
  const { data: latestIndexAttempts, error } = useSWR<PaginatedIndexAttempts>(
    SWR_KEYS.ccPairLatestIndexAttempt(ccPair.id),
    errorHandlingFetcher,
    { refreshInterval: POLL_MS }
  );
  // Waits for the latest attempt, so a running pair never flashes as indexed.
  if (latestIndexAttempts === undefined && error === undefined) {
    return <CardLoader descriptionLines={2} />;
  }
  const latestIndexAttempt = latestIndexAttempts?.items[0];
  const status = ccPairStatusTag(
    ccPair.status,
    ccPair.in_repeated_error_state,
    latestIndexAttempt?.status
  );
  const speed =
    ccPair.indexing &&
    ccPair.overall_indexing_speed !== null &&
    ccPair.num_docs_indexed > 0
      ? ccPair.overall_indexing_speed.toLocaleString(locale, {
          minimumFractionDigits: 1,
          maximumFractionDigits: 1,
        })
      : null;
  const recent = latestIndexAttempt?.total_docs_indexed ?? 0;

  const chart = !FIRST_RUN_STATUSES.has(ccPair.status);

  return (
    <Card
      border="solid"
      rounding={4}
      padding={2}
      data-testid="connector-indexing-status"
    >
      <Section alignItems="stretch" gap={1} height="fit">
        <Section
          flexDirection="row"
          alignItems="start"
          justifyContent="start"
          gap={1}
          height="fit"
          wrap
        >
          <StatBlock>
            <Tag
              icon={status.icon}
              title={tBadges(status.labelKey)}
              color={status.color}
            />
            <Text font="secondary-body" color="text-03">
              {t("title")}
            </Text>
            <Text font="secondary-body" color="text-03">
              {speed === null
                ? t("lastIndexed.value", {
                    when: timeAgo(ccPair.last_indexed, locale) ?? "-",
                  })
                : t("indexingSpeed", { speed })}
            </Text>
          </StatBlock>
          <StatBlock>
            <Section
              flexDirection="row"
              justifyContent="start"
              alignItems="end"
              gap={1}
              width="fit"
              height="fit"
            >
              <Text font="main-content-emphasis" color="text-04">
                {recent.toLocaleString(locale)}
              </Text>
              <Text font="main-content-body" color="text-04">
                {t("documents.total", {
                  total: ccPair.num_docs_indexed.toLocaleString(locale),
                })}
              </Text>
            </Section>
            <Text font="secondary-body" color="text-03">
              {t("documents.label")}
            </Text>
            <Text font="secondary-body" color="text-03">
              {t("documentsIndexed.label")}
            </Text>
          </StatBlock>
          {chart && (
            <Section
              flexDirection="row"
              justifyContent="end"
              width="auto"
              height="fit"
              className="grow basis-0"
            >
              <Dropdown>
                <Dropdown.Trigger asChild>
                  <OpenButton icon={SvgClock} state="empty">
                    {tWindow(WINDOW_LABEL_KEYS[range])}
                  </OpenButton>
                </Dropdown.Trigger>
                <Dropdown.Data
                  label={tWindow("label")}
                  value={range}
                  onSelect={(option) => {
                    const picked = WINDOWS.find((w) => w === option.value);
                    if (picked !== undefined) setRange(picked);
                  }}
                  items={WINDOWS.map((window) => ({
                    kind: "option" as const,
                    value: window,
                    title: tWindow(WINDOW_LABEL_KEYS[window]),
                  }))}
                />
              </Dropdown>
            </Section>
          )}
        </Section>
        {chart && (
          <Section padding={2} alignItems="stretch" height="fit">
            <ThroughputChart ccPairId={ccPair.id} range={range} />
          </Section>
        )}
      </Section>
    </Card>
  );
}
