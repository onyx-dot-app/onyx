"use client";

import Link from "next/link";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { Button, Card, Popover, Tag, Text } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import {
  SvgAlertTriangle,
  SvgExpand,
  SvgFold,
  SvgOrganization,
  SvgSettings,
  SvgUser,
  SvgUsers,
  SvgUserSync,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { timeAgo } from "@opal/time";
import type { IndexingConnectorRow } from "@/lib/connectors/types";
import { getDocsProcessedPerMinute } from "@/lib/indexAttempt";
import { getSourceMetadata } from "@/lib/connectors/utils";
import { can } from "@/lib/permissions/resource-actions";
import type { AccessType } from "@/lib/types";
import { DocCounts } from "@/views/admin/connectors/ConnectorDetailPage/RunRow";
import RunsCard from "@/views/admin/connectors/ConnectorDetailPage/RunsCard";
import { connectorRowStatusTag } from "@/views/admin/connectors/ConnectorDetailPage/statusTag";
import StageDetailsPopoverContent, {
  StageDetailsTrigger,
} from "@/views/admin/connectors/ConnectorDetailPage/StageDetailsPopover";

const ACCESS_ICONS = {
  public: SvgOrganization,
  private: SvgUsers,
  sync: SvgUserSync,
  sync_restricted: SvgUserSync,
} satisfies Record<AccessType, IconFunctionComponent>;

export interface ConnectorRowProps {
  row: IndexingConnectorRow;
  /** Shows the connector's run history under its summary. */
  expanded: boolean;
  onToggle: () => void;
}

/** One connector in the status page's list: what it is, how its latest run stands, and the documents it holds. */
export default function ConnectorRow({
  row,
  expanded,
  onToggle,
}: ConnectorRowProps) {
  const t = useTranslations("admin.indexing.list");
  const tRuns = useTranslations("admin.connector.runs");
  const tBadges = useTranslations("admin.status.badges");
  const locale = useLocale();
  const format = useFormatter();
  const attempt = row.latest_index_attempt;
  // The old table linked a row only when the viewer could operate the pair.
  const canOperate = can(row, "operate");
  const tag = connectorRowStatusTag(
    row.cc_pair_status,
    row.status,
    attempt?.status
  );
  const warnings = attempt?.error_count ?? 0;
  // An empty display name falls back to the email, as an unset one does.
  const owner = row.creator_name?.trim() || row.creator_email;
  const toggleLabel = expanded ? t("actions.collapse") : t("actions.expand");

  // What the status line adds: the live rate, the place in line, or when it last ran.
  function detail(): string {
    switch (row.status) {
      case "indexing": {
        const rate = getDocsProcessedPerMinute(attempt);
        if (rate === null) return tRuns("detail.running");
        return tRuns("detail.rate", {
          rate: format.number(rate, { maximumFractionDigits: 2 }),
        });
      }
      case "scheduled":
        if (row.queue_position !== null) {
          return t("detail.queued", { position: row.queue_position });
        }
        // A canceled or interrupted run reads like a finished one until the next run queues.
        if (attempt === null || attempt.time_finished === null) {
          return tRuns("detail.queued");
        }
        return timeAgo(attempt.time_finished, locale) ?? "-";
      case "paused":
        return row.last_success === null
          ? t("detail.neverIndexed")
          : t("detail.lastIndexed", {
              when: timeAgo(row.last_success, locale) ?? "-",
            });
      default: {
        const ended = attempt?.time_finished ?? row.last_success;
        return ended === null
          ? t("detail.neverIndexed")
          : (timeAgo(ended, locale) ?? "-");
      }
    }
  }

  // The stage details popover spans the row, so the row is its anchor.
  return (
    <Popover>
      <Popover.Anchor asChild>
        <Card
          border="solid"
          rounding={4}
          padding={2}
          data-testid={`indexing-connector-${row.cc_pair_id}`}
        >
          <Section alignItems="stretch" gap={1} height="fit">
            <Section
              flexDirection="row"
              alignItems="start"
              justifyContent="start"
              gap={1}
              padding={1}
              height="fit"
            >
              <Section
                alignItems="start"
                gap={1}
                padding={1}
                height="fit"
                className="min-w-0 flex-1"
              >
                {canOperate ? (
                  <Link
                    href={`/admin/connector/${row.cc_pair_id}`}
                    className="hover:underline"
                  >
                    <Content
                      icon={getSourceMetadata(row.source).icon}
                      title={row.name}
                      sizePreset="main-ui"
                      variant="section"
                    />
                  </Link>
                ) : (
                  <Content
                    icon={getSourceMetadata(row.source).icon}
                    title={row.name}
                    sizePreset="main-ui"
                    variant="section"
                  />
                )}
                <Section
                  flexDirection="row"
                  justifyContent="start"
                  gap={1}
                  height="fit"
                  wrap
                >
                  <Content
                    icon={ACCESS_ICONS[row.access_type]}
                    title={t(`access.${row.access_type}`)}
                    sizePreset="secondary"
                    variant="body"
                    color="muted"
                    width="fit"
                  />
                  {owner !== null && (
                    <Content
                      icon={SvgUser}
                      title={owner}
                      sizePreset="secondary"
                      variant="body"
                      color="muted"
                      width="fit"
                    />
                  )}
                </Section>
              </Section>

              <Section
                alignItems="start"
                gap={1}
                padding={1}
                width={13}
                height="fit"
                className="shrink-0"
              >
                <Section
                  flexDirection="row"
                  justifyContent="start"
                  gap={1}
                  width="fit"
                  height="fit"
                >
                  <Tag
                    icon={tag.icon}
                    title={tBadges(tag.labelKey)}
                    color={tag.color}
                  />
                  {attempt !== null && <StageDetailsTrigger />}
                  {warnings > 0 && (
                    <Tag
                      icon={SvgAlertTriangle}
                      title={format.number(warnings)}
                      tooltip={tRuns("warnings.tooltip", { count: warnings })}
                      color="amber"
                    />
                  )}
                </Section>
                <Text font="secondary-body" color="text-03">
                  {detail()}
                </Text>
              </Section>

              <Section
                alignItems="end"
                gap={1}
                padding={1}
                width={10}
                height="fit"
                className="shrink-0"
              >
                <Section
                  flexDirection="row"
                  justifyContent="end"
                  alignItems="end"
                  gap={1}
                  width="fit"
                  height="fit"
                >
                  <Text font="main-ui-action" color="text-04">
                    {row.status === "indexing" && attempt !== null
                      ? t("docs.recentOfTotal", {
                          recent: format.number(attempt.total_docs_indexed),
                          total: format.number(row.docs_indexed),
                        })
                      : format.number(row.docs_indexed)}
                  </Text>
                  <Text font="secondary-body" color="text-03">
                    {t("docs.label")}
                  </Text>
                </Section>
                {attempt !== null && <DocCounts attempt={attempt} />}
              </Section>

              <Section
                flexDirection="row"
                justifyContent="end"
                alignItems="center"
                gap={1}
                width="fit"
                height="fit"
                className="shrink-0"
              >
                {canOperate && (
                  <Button
                    icon={SvgSettings}
                    prominence="tertiary"
                    size="sm"
                    href={`/admin/connector/${row.cc_pair_id}`}
                    tooltip={t("actions.manage")}
                    aria-label={t("actions.manage")}
                  />
                )}
                <Button
                  icon={expanded ? SvgFold : SvgExpand}
                  prominence="tertiary"
                  size="sm"
                  tooltip={toggleLabel}
                  aria-label={toggleLabel}
                  aria-expanded={expanded}
                  onClick={onToggle}
                />
              </Section>
            </Section>
            {expanded && (
              <RunsCard
                ccPairId={row.cc_pair_id}
                canOperate={canOperate}
                embedded
              />
            )}
          </Section>
        </Card>
      </Popover.Anchor>
      {attempt !== null && (
        <StageDetailsPopoverContent indexAttemptId={attempt.id} />
      )}
    </Popover>
  );
}
