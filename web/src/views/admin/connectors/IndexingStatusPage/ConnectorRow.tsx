"use client";

import { NavLink, useNavigation } from "@opal/navigation";
import { useEffect, useState } from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import {
  Button,
  Card,
  Divider,
  Popover,
  Badge,
  Text,
  Tooltip,
  BadgeButton,
} from "@opal/components";
import { Content, Section } from "@opal/layouts";
import {
  SvgChevronRight,
  SvgDocFile,
  SvgExpand,
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
import { cn } from "@opal/utils";
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
import RunsCard from "@/views/admin/connectors/ConnectorDetailPage/RunsCard";
import { focusDimClass } from "@/views/admin/connectors/ConnectorDetailPage/focusMode";
import {
  connectorRowStatusTag,
  ERROR_COUNT_TAG,
} from "@/views/admin/connectors/ConnectorDetailPage/statusTag";
import StageDetailsPopoverContent, {
  StageDetailsTrigger,
} from "@/views/admin/connectors/ConnectorDetailPage/StageDetailsPopover";
import LineLayout, {
  LINE_NARROW_HIDDEN,
  LineIconLabel,
  LineTags,
} from "@/views/admin/connectors/shared/LineLayout";

const ACCESS_ICONS = {
  public: SvgOrganization,
  private: SvgUsers,
  sync: SvgUserSync,
  sync_restricted: SvgUserSync,
  personal: SvgUser,
} satisfies Record<AccessType, IconFunctionComponent>;

export interface ConnectorRowProps {
  row: IndexingConnectorRow;
  /** Shows the connector's run history under its summary. */
  expanded: boolean;
  onToggle: () => void;
  /** Opens the activity history on this connector's runs. */
  onViewLogs: () => void;
  /** Shows this connector's open errors. */
  onFocusError: () => void;
  /** Another connector holds the focus, so this one steps back. */
  dimmed: boolean;
  /** Called when this connector's stage popover, or one of its runs' popovers, opens or closes. */
  onFocusChange: (ccPairId: number, focused: boolean) => void;
  /** One of this connector's activities is hovered in the panel. */
  lifted?: boolean;
}

/** One connector in the status page's list: what it is, how its latest run stands, and the documents it holds. */
export default function ConnectorRow({
  row,
  expanded,
  onToggle,
  onViewLogs,
  onFocusError,
  dimmed,
  onFocusChange,
  lifted = false,
}: ConnectorRowProps) {
  const t = useTranslations("admin.indexing.list");
  const navigation = useNavigation();
  const tRuns = useTranslations("admin.connector.runs");
  const locale = useLocale();
  const format = useFormatter();
  const attempt = row.latest_index_attempt;
  // Only an operator opens the connector page or pauses the pair, so the actions stay in place but disabled.
  const canOperate = can(row, "operate");
  const tag = connectorRowStatusTag(
    row.cc_pair_status,
    row.status,
    attempt?.status
  );
  // Open errors only, so the badge clears once Retry or Resolve closes them.
  const warnings = row.open_error_count;
  // The latest run's processed documents. A deleting pair is losing its documents, so its count says nothing.
  const recentlyProcessed =
    row.status === "deleting" ? 0 : (attempt?.total_docs_indexed ?? 0);
  // A paused, scheduled or deleting row has no run in flight, so its stages stay hidden.
  const idle =
    row.status === "paused" ||
    row.status === "scheduled" ||
    row.status === "deleting";
  const toggleLabel = expanded ? t("actions.collapse") : t("actions.expand");
  const [stagesOpen, setStagesOpen] = useState(false);
  const [runsFocused, setRunsFocused] = useState(false);
  const focused = stagesOpen || runsFocused;
  const ccPairId = row.cc_pair_id;
  const connectorHref = `/admin/connector/${ccPairId}` as const;
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
      <Button
        icon={paused ? SvgPlayCircle : SvgPause}
        prominence="tertiary"
        size="md"
        tooltip={pauseLabel}
        aria-label={pauseLabel}
        disabled={!canPause || isUpdating}
        onClick={() =>
          void handleStatusChange(
            paused
              ? ConnectorCredentialPairStatus.ACTIVE
              : ConnectorCredentialPairStatus.PAUSED
          )
        }
      />
      <Button
        icon={SvgDocFile}
        prominence="tertiary"
        size="md"
        tooltip={tRuns("actions.logs")}
        aria-label={tRuns("actions.logs")}
        onClick={onViewLogs}
      />
    </Section>
  );

  // The whole line is one real link, not Divider's footer button, so it opens
  // in a new tab too. The chevron's 10 px end inset centers it under the
  // expand button; 6 px above and below make the line 36 px tall.
  const viewAllRuns = (
    <NavLink href={`${connectorHref}?tab=indexing`} className="group block">
      <Section flexDirection="row" alignItems="center" gap={0} height="fit">
        <Section height="fit" className="min-w-0 flex-1">
          <Divider title={t("actions.viewAllRuns")} />
        </Section>
        <Section
          width="fit"
          height="fit"
          padding={1}
          className="my-1.5 ms-1.5 me-2.5 rounded-08 group-hover:bg-background-tint-02"
        >
          <SvgChevronRight size={16} className="stroke-text-03" />
        </Section>
      </Section>
    </NavLink>
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
            shadow={expanded || focused || lifted ? "sm" : "none"}
            data-testid={`indexing-connector-${row.cc_pair_id}`}
          >
            <Section alignItems="stretch" gap={0} height="fit">
              {/* Expanded, the run filters close the bottom of this region, 4 px under the line. */}
              <Section
                alignItems="stretch"
                width="auto"
                height="fit"
                className={cn("m-2", expanded && "mb-0")}
              >
                <LineLayout
                  variant="row"
                  a={
                    <>
                      {/* The link spans the column so the clamped title truncates at its edge. */}
                      {canOperate ? (
                        <NavLink
                          href={connectorHref}
                          className="w-full hover:underline"
                        >
                          <Content
                            icon={getSourceMetadata(row.source).icon}
                            title={row.name}
                            titleMaxLines={1}
                            font="main-ui-action"
                          />
                        </NavLink>
                      ) : (
                        <Content
                          icon={getSourceMetadata(row.source).icon}
                          title={row.name}
                          titleMaxLines={1}
                          font="main-ui-action"
                        />
                      )}
                      {/* Below 640 px A shares its line with D, so it is the name alone and the wrapped row stays two lines tall. */}
                      <Section
                        alignItems="start"
                        height="fit"
                        className={LINE_NARROW_HIDDEN}
                      >
                        <LineIconLabel
                          icon={ACCESS_ICONS[row.access_type]}
                          label={t(`access.${row.access_type}`, {
                            count: row.group_count,
                          })}
                        />
                      </Section>
                    </>
                  }
                  b={
                    <>
                      <LineTags tag={tag}>
                        {attempt !== null && !idle && (
                          <StageDetailsTrigger open={stagesOpen} />
                        )}
                        {warnings > 0 && (
                          <BadgeButton
                            {...ERROR_COUNT_TAG}
                            title={format.number(warnings)}
                            titleColor="text-04"
                            tooltip={t("actions.viewErrors")}
                            onClick={onFocusError}
                          />
                        )}
                      </LineTags>
                      <Text font="secondary-body" color="text-03">
                        {detail()}
                      </Text>
                    </>
                  }
                  c={
                    <>
                      {/* Each count keeps one line in the narrow column, cut at its end. */}
                      {row.docs_indexed > 0 && (
                        <Section
                          flexDirection="row"
                          justifyContent="end"
                          alignItems="end"
                          gap={1}
                          height="fit"
                        >
                          <Text
                            maxLines={1}
                            overflowTooltip
                            font="main-ui-action"
                            color="text-04"
                          >
                            {format.number(row.docs_indexed)}
                          </Text>
                          <Text font="secondary-body" color="text-03">
                            {t("docs.label")}
                          </Text>
                        </Section>
                      )}
                      {recentlyProcessed > 0 && (
                        <Section
                          flexDirection="row"
                          justifyContent="end"
                          height="fit"
                        >
                          <Tooltip
                            tooltip={
                              row.status === "indexing"
                                ? t("docs.processedTooltip.running")
                                : t("docs.processedTooltip.finished")
                            }
                            side="top"
                          >
                            <Text
                              font="secondary-body"
                              color="text-03"
                              maxLines={1}
                            >
                              {t("docs.processed", {
                                count: recentlyProcessed,
                              })}
                            </Text>
                          </Tooltip>
                        </Section>
                      )}
                    </>
                  }
                  d={
                    <>
                      <Button
                        icon={SvgSettings}
                        prominence="tertiary"
                        size="md"
                        {...navigation.linkTo(connectorHref)}
                        tooltip={t("actions.manage")}
                        aria-label={t("actions.manage")}
                        disabled={!canOperate}
                      />
                      <Button
                        icon={expanded ? SvgFold : SvgExpand}
                        prominence="tertiary"
                        size="md"
                        tooltip={toggleLabel}
                        aria-label={toggleLabel}
                        aria-expanded={expanded}
                        onClick={onToggle}
                      />
                    </>
                  }
                />
              </Section>
              {expanded && (
                <RunsCard
                  ccPairId={row.cc_pair_id}
                  canOperate={canOperate}
                  embedded
                  actions={runActions}
                  footer={viewAllRuns}
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
