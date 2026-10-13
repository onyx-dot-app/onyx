"use client";

import { useLocale, useTranslations } from "next-intl";
import useSWR from "swr";
import { Card, Tag, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { CardLoader } from "@opal/loaders";
import { timeAgo } from "@opal/time";
import type {
  CCPairFullInfo,
  PaginatedIndexAttempts,
} from "@/lib/connectors/types";
import { isPermSynced } from "@/lib/connectors/accessType";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { PermissionSyncStatusBadge } from "@/views/admin/connectors/ConnectorDetailPage/PermissionSyncStatusBadge";
import { ccPairStatusTag } from "@/views/admin/connectors/ConnectorDetailPage/statusTag";

interface StatBlockProps {
  children: React.ReactNode;
}
/** One column of the card: a figure or tag over its two-line label. */
function StatBlock({ children }: StatBlockProps) {
  return (
    // Columns share the row evenly and wrap below 12rem.
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

/** The pair at a glance: status, latest and total documents, last run, and sync state when synced. */
export default function StatusCard({ ccPair }: StatusCardProps) {
  const t = useTranslations("admin.connector.statusCard");
  const tBadges = useTranslations("admin.status.badges");
  const locale = useLocale();
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
  const lastSynced =
    ccPair.last_permission_sync_attempt_finished ??
    ccPair.last_full_permission_sync;

  return (
    <Card
      border="solid"
      rounding={4}
      padding={2}
      data-testid="connector-indexing-status"
    >
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
        {isPermSynced(ccPair.access_type) && (
          <StatBlock>
            <PermissionSyncStatusBadge
              status={ccPair.last_permission_sync_attempt_status}
              errorMsg={ccPair.last_permission_sync_attempt_error_message}
            />
            <Text font="secondary-body" color="text-03">
              {t("permissionSyncing.label")}
            </Text>
            <Text font="secondary-body" color="text-03">
              {t("lastSynced.value", {
                when: timeAgo(lastSynced, locale) ?? "-",
              })}
            </Text>
          </StatBlock>
        )}
      </Section>
    </Card>
  );
}
