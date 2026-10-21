"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { Button, Card, Popover, Tag, Text } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import {
  SvgAlertTriangle,
  SvgExpand,
  SvgFileText,
  SvgFold,
  SvgOrganization,
  SvgPause,
  SvgPlayCircle,
  SvgSettings,
  SvgUser,
  SvgUsers,
  SvgUserSync,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { timeAgo } from "@opal/time";
import {
  ConnectorCredentialPairStatus,
  type IndexingConnectorRow,
} from "@/lib/connectors/types";
import { useStatusChange } from "@/lib/connectors/ccPair/hooks";
import { getDocsProcessedPerMinute } from "@/lib/indexAttempt";
import {
  getSourceMetadata,
  statusIsNotCurrentlyActive,
} from "@/lib/connectors/utils";
import { can } from "@/lib/permissions/resource-actions";
import type { AccessType } from "@/lib/types";
import { DocCounts } from "@/views/admin/connectors/ConnectorDetailPage/RunRow";
import RunsCard from "@/views/admin/connectors/ConnectorDetailPage/RunsCard";
import { focusDimClass } from "@/views/admin/connectors/ConnectorDetailPage/focusMode";
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
  /** Opens the activity history on this connector's runs. */
  onViewLogs: () => void;
  /** Another connector holds the focus, so this one steps back. */
  dimmed: boolean;
  /** Called when this connector's stage popover, or one of its runs' popovers, opens or closes. */
  onFocusChange: (ccPairId: number, focused: boolean) => void;
}

/** One connector in the status page's list: what it is, how its latest run stands, and the documents it holds. */
export default function ConnectorRow({
  row,
  expanded,
  onToggle,
  onViewLogs,
  dimmed,
  onFocusChange,
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
  // A paused or scheduled row has no run in flight, so its stages and file counts stay hidden.
  const idle = row.status === "paused" || row.status === "scheduled";
  const toggleLabel = expanded ? t("actions.collapse") : t("actions.expand");
  const [stagesOpen, setStagesOpen] = useState(false);
  const [runsFocused, setRunsFocused] = useState(false);
  const focused = stagesOpen || runsFocused;
  const ccPairId = row.cc_pair_id;
  useEffect(() => {
    onFocusChange(ccPairId, focused);
  }, [ccPairId, focused, onFocusChange]);
  useEffect(
    () => () => onFocusChange(ccPairId, false),
    [ccPairId, onFocusChange]
  );
  const { handleStatusChange, isUpdating, ConfirmModal } = useStatusChange({
    id: ccPairId,
    name: row.name,
    status: row.cc_pair_status,
  });
  const paused = statusIsNotCurrentlyActive(row.cc_pair_status);
  const pauseLabel = paused ? t("actions.resume") : t("actions.pause");
  const canPause =
    canOperate && row.cc_pair_status !== ConnectorCredentialPairStatus.DELETING;

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

  const runActions = (
    <Section
      flexDirection="row"
      alignItems="center"
      gap={1}
      width="fit"
      height="fit"
      className="shrink-0"
    >
      {canPause && (
        <Button
          icon={paused ? SvgPlayCircle : SvgPause}
          prominence="tertiary"
          size="sm"
          tooltip={pauseLabel}
          aria-label={pauseLabel}
          disabled={isUpdating}
          onClick={() =>
            void handleStatusChange(
              paused
                ? ConnectorCredentialPairStatus.ACTIVE
                : ConnectorCredentialPairStatus.PAUSED
            )
          }
        />
      )}
      <Button
        icon={SvgFileText}
        prominence="tertiary"
        size="sm"
        tooltip={tRuns("actions.logs")}
        aria-label={tRuns("actions.logs")}
        onClick={onViewLogs}
      />
    </Section>
  );

  // The stage details popover spans the row, so the row is its anchor. The run list sits flush against the card's edges.
  return (
    <Section
      alignItems="stretch"
      height="fit"
      className={focusDimClass(dimmed)}
    >
      {ConfirmModal}
      <Popover open={stagesOpen} onOpenChange={setStagesOpen}>
        <Popover.Anchor asChild>
          <Card
            border="solid"
            rounding={4}
            padding={0}
            shadow={expanded || focused ? "sm" : "none"}
            data-testid={`indexing-connector-${row.cc_pair_id}`}
          >
            <Section alignItems="stretch" gap={0} height="fit">
              <Section alignItems="stretch" height="fit">
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
                    {/* The link spans the column so the clamped title truncates at its edge. */}
                    {canOperate ? (
                      <Link
                        href={`/admin/connector/${row.cc_pair_id}`}
                        className="w-full hover:underline"
                      >
                        <Content
                          icon={getSourceMetadata(row.source).icon}
                          title={row.name}
                          titleMaxLines={1}
                          sizePreset="main-ui"
                          variant="section"
                        />
                      </Link>
                    ) : (
                      <Content
                        icon={getSourceMetadata(row.source).icon}
                        title={row.name}
                        titleMaxLines={1}
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
                        variant="status"
                        font="secondary-body"
                      />
                      {attempt !== null && !idle && (
                        <StageDetailsTrigger open={stagesOpen} />
                      )}
                      {warnings > 0 && (
                        <Tag
                          icon={SvgAlertTriangle}
                          title={format.number(warnings)}
                          tooltip={tRuns("warnings.tooltip", {
                            count: warnings,
                          })}
                          color="orange"
                          variant="count"
                          font="secondary-body"
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
                    {attempt !== null && !idle && (
                      <DocCounts attempt={attempt} />
                    )}
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
              </Section>
              {expanded && (
                <RunsCard
                  ccPairId={row.cc_pair_id}
                  canOperate={canOperate}
                  embedded
                  actions={runActions}
                  onFocusChange={setRunsFocused}
                />
              )}
            </Section>
          </Card>
        </Popover.Anchor>
        {attempt !== null && (
          <StageDetailsPopoverContent indexAttemptId={attempt.id} />
        )}
      </Popover>
    </Section>
  );
}
