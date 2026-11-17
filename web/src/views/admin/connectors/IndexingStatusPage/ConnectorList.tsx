"use client";

import { useNavigation } from "@opal/navigation";
import { useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import useSWR from "swr";
import {
  Button,
  Card,
  Divider,
  Dropdown,
  SelectButton,
  InputTypeIn,
  MessageCard,
  Pagination,
  BadgeButton,
} from "@opal/components";
import { useDebouncedValue } from "@opal/hooks";
import { Content, IllustrationContent, Section } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import { CardLoader } from "@opal/loaders";
import { SvgActivity, SvgSettings } from "@opal/icons";
import { markdown } from "@opal/utils";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  INDEXING_CONNECTOR_STATUSES,
  type IndexingConnectorStatus,
  type IndexingConnectorRow,
  type IndexingConnectorsResponse,
} from "@/lib/connectors/types";
import { getSourceMetadata } from "@/lib/connectors/utils";
import type { ValidSources } from "@/lib/connectors/types/source";
import type { FederatedConnectorStatus } from "@/lib/types";
import {
  focusDimClass,
  useFocusedRow,
} from "@/views/admin/connectors/ConnectorDetailPage/focusMode";
import { bucketStatusTag } from "@/views/admin/connectors/ConnectorDetailPage/statusTag";
import ConnectorRow from "@/views/admin/connectors/IndexingStatusPage/ConnectorRow";
import {
  SEARCH_DELAY_MS,
  SEARCH_MAX_LENGTH,
} from "@/views/admin/connectors/shared/search";

const PAGE_SIZE = 20;
const POLL_MS = 30_000;
const LOADER_ROWS = 5;
const ALL = "all";
/** The live buckets, which the toolbar counts and filters as one running pill. */
const RUNNING_STATUSES = [
  "indexing",
  "syncing",
] as const satisfies readonly IndexingConnectorStatus[];
const RUNNING = "running" as const;
type StatusFilter = IndexingConnectorStatus | typeof RUNNING;
/** The buckets with a pill of their own, in rank order. */
const OWN_PILL_STATUSES = INDEXING_CONNECTOR_STATUSES.filter(
  (
    bucket
  ): bucket is Exclude<
    IndexingConnectorStatus,
    (typeof RUNNING_STATUSES)[number]
  > => !RUNNING_STATUSES.some((running) => running === bucket)
);

/** The buckets a filter asks the API for, or null for every pair. */
function filterStatuses(
  filter: StatusFilter | null
): readonly IndexingConnectorStatus[] | null {
  if (filter === null) return null;
  return filter === RUNNING ? RUNNING_STATUSES : [filter];
}

interface FederatedRowProps {
  connector: FederatedConnectorStatus;
}
/** A federated connector: searched at query time, so it has no runs or documents. */
function FederatedRow({ connector }: FederatedRowProps) {
  const t = useTranslations("admin.indexing.list");
  const navigation = useNavigation();
  return (
    <Card border="solid" rounding={4} padding={2}>
      <Section
        flexDirection="row"
        alignItems="center"
        justifyContent="between"
        gap={1}
        padding={2}
        height="fit"
      >
        {/* The name column shrinks before the button, so the clamp has an edge. */}
        <Section alignItems="start" height="fit" className="min-w-0 flex-1">
          <Content
            icon={getSourceMetadata(connector.source).icon}
            title={connector.name}
            titleMaxLines={1}
            font="main-ui-action"
            badge={{ title: t("federated.tag"), color: "default" }}
          />
        </Section>
        <Button
          icon={SvgSettings}
          prominence="tertiary"
          size="sm"
          {...navigation.linkTo(`/admin/federated/${connector.id}`)}
          tooltip={t("actions.manageFederated")}
          aria-label={t("actions.manageFederated")}
        />
      </Section>
    </Card>
  );
}

/** The page's rows by source, sources in the order their first row appears. */
function groupBySource(
  rows: IndexingConnectorRow[]
): [ValidSources, IndexingConnectorRow[]][] {
  const groups = new Map<ValidSources, IndexingConnectorRow[]>();
  for (const row of rows) {
    const group = groups.get(row.source);
    if (group === undefined) groups.set(row.source, [row]);
    else group.push(row);
  }
  return Array.from(groups);
}

/** Every readable connector, searched and filtered by status, with its latest run at a glance. */
export interface ConnectorListProps {
  /** Opens the activity history on one connector's runs. */
  onViewLogs: (row: IndexingConnectorRow) => void;
  /** Shows one connector's open errors. */
  onFocusError: (row: IndexingConnectorRow) => void;
  /** Called when a connector's popover opens or closes, so the page can step back around the list. */
  onFocusChange?: (focused: boolean) => void;
  /** The connector whose activity is hovered in the panel, so its row lifts. */
  liftedCcPairId?: number | null;
}

export default function ConnectorList({
  onViewLogs,
  onFocusError,
  onFocusChange,
  liftedCcPairId = null,
}: ConnectorListProps) {
  const t = useTranslations("admin.indexing.list");
  const tBadges = useTranslations("admin.status.badges");
  const format = useFormatter();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<StatusFilter | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const search = useDebouncedValue(searchInput.trim(), SEARCH_DELAY_MS);
  // A connector's open popover steps the other connectors back.
  const focus = useFocusedRow<number>(onFocusChange);
  // One row opens at a time, so the page polls one pair's runs.
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const { data, error, isLoading } = useSWR<IndexingConnectorsResponse>(
    SWR_KEYS.indexMonitoringConnectors({
      pageNum: page - 1,
      pageSize: PAGE_SIZE,
      q: search,
      status: filterStatuses(status),
    }),
    errorHandlingFetcher,
    { refreshInterval: POLL_MS, keepPreviousData: true }
  );

  function pickStatus(next: StatusFilter | null) {
    setStatus(next);
    setPage(1);
  }

  const totalItems = data?.total_items ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalItems / PAGE_SIZE));
  // Polling can shrink the list under an open page.
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);
  const filtered = status !== null || search !== "";
  const indexingCount = data?.status_counts.indexing ?? 0;
  const syncingCount = data?.status_counts.syncing ?? 0;
  const empty =
    data !== undefined &&
    data.items.length === 0 &&
    data.federated_connectors.length === 0;

  return (
    <Section alignItems="stretch" gap={2} height="fit">
      {/* Inset at the sides only. The pills wrap onto their own line when the search and filter leave them no room. */}
      <Section
        width="auto"
        flexDirection="row"
        justifyContent="start"
        alignItems="center"
        gap={2}
        height="fit"
        wrap
        className="mx-2"
      >
        <Section height="fit" className="min-w-40 flex-1">
          <InputTypeIn
            icon="search"
            variant="internal"
            placeholder={t("search.placeholder")}
            maxLength={SEARCH_MAX_LENGTH}
            value={searchInput}
            onChange={(event) => {
              setSearchInput(event.target.value);
              setPage(1);
            }}
          />
        </Section>
        <Dropdown>
          <Dropdown.Trigger asChild>
            <SelectButton
              variant="select-filter"
              chevron
              labelFont="main-ui-action"
              icon={SvgActivity}
              state={status !== null ? "selected" : "empty"}
              onClear={() => pickStatus(null)}
            >
              {status === null
                ? t("statusFilter.all")
                : status === RUNNING
                  ? t("statusFilter.running")
                  : tBadges(status)}
            </SelectButton>
          </Dropdown.Trigger>
          <Dropdown.Data
            label={t("statusFilter.label")}
            value={status ?? ALL}
            onSelect={(option) =>
              pickStatus(
                INDEXING_CONNECTOR_STATUSES.find(
                  (candidate) => candidate === option.value
                ) ?? null
              )
            }
            items={[
              {
                kind: "option" as const,
                value: ALL,
                title: t("statusFilter.all"),
              },
              ...INDEXING_CONNECTOR_STATUSES.map((candidate) => ({
                kind: "option" as const,
                value: candidate,
                title: tBadges(candidate),
              })),
            ]}
          />
        </Dropdown>
        <Section
          flexDirection="row"
          justifyContent="start"
          gap={2}
          padding={1.5}
          width="fit"
          height="fit"
        >
          {/* A pill per filter that holds a pair under the search, whatever the status filter. A click filters to it, and again clears it. */}
          {[
            {
              filter: RUNNING,
              count: indexingCount + syncingCount,
              tag: bucketStatusTag("indexing"),
              tooltip: t("counts.running", {
                indexing: indexingCount,
                syncing: syncingCount,
              }),
            },
            ...OWN_PILL_STATUSES.map((bucket) => {
              const count = data?.status_counts[bucket] ?? 0;
              return {
                filter: bucket,
                count,
                tag: bucketStatusTag(bucket),
                tooltip: t(`counts.${bucket}`, { count }),
              };
            }),
          ]
            .filter(({ count }) => count > 0)
            .map(({ filter, count, tag, tooltip }) => (
              <BadgeButton
                key={filter}
                icon={tag.icon}
                title={format.number(count)}
                color={tag.color}
                titleColor="text-04"
                size={6}
                tooltip={tooltip}
                pressed={status === filter}
                onClick={() => pickStatus(status === filter ? null : filter)}
              />
            ))}
        </Section>
      </Section>

      {error !== undefined ? (
        <MessageCard variant="error" title={t("loadError")} />
      ) : isLoading && data === undefined ? (
        <Section alignItems="stretch" gap={2} height="fit">
          {Array.from({ length: LOADER_ROWS }, (_, index) => (
            <CardLoader key={index} rounding={4} padding={2} />
          ))}
        </Section>
      ) : empty ? (
        <IllustrationContent
          illustration={SvgNoResult}
          title={filtered ? t("empty.filteredTitle") : t("empty.title")}
          description={filtered ? undefined : markdown(t("empty.description"))}
        />
      ) : (
        <Section alignItems="stretch" gap={2} height="fit">
          {groupBySource(data?.items ?? []).map(([source, rows]) => (
            <Divider
              key={source}
              foldable
              defaultOpen
              chevronPosition="start"
              // A folded group keeps its rows mounted, so its expanded row closes to stop polling runs nobody sees.
              onOpenChange={(open) => {
                if (open) return;
                setExpandedId((current) =>
                  rows.some((row) => row.cc_pair_id === current)
                    ? null
                    : current
                );
              }}
              title={t("sourceGroup", {
                source: getSourceMetadata(source).displayName,
                // The API counts every source on the page, so the fallback only satisfies the partial type.
                count: data?.source_counts[source] ?? rows.length,
              })}
            >
              <Section alignItems="stretch" gap={2} height="fit">
                {rows.map((row) => (
                  <ConnectorRow
                    key={row.cc_pair_id}
                    row={row}
                    expanded={expandedId === row.cc_pair_id}
                    onToggle={() =>
                      setExpandedId((open) =>
                        open === row.cc_pair_id ? null : row.cc_pair_id
                      )
                    }
                    onViewLogs={() => onViewLogs(row)}
                    onFocusError={() => onFocusError(row)}
                    dimmed={focus.isDimmed(row.cc_pair_id)}
                    onFocusChange={focus.setOpen}
                    lifted={row.cc_pair_id === liftedCcPairId}
                  />
                ))}
              </Section>
            </Divider>
          ))}
          {data?.federated_connectors.map((connector) => (
            <Section
              key={connector.id}
              alignItems="stretch"
              height="fit"
              className={focusDimClass(focus.focused)}
            >
              <FederatedRow connector={connector} />
            </Section>
          ))}
        </Section>
      )}

      {totalItems > PAGE_SIZE && (
        <Pagination
          variant="count"
          currentPage={page}
          totalPages={totalPages}
          pageSize={PAGE_SIZE}
          totalItems={totalItems}
          onChange={setPage}
          units={t("units", { count: totalItems })}
          size="sm"
        />
      )}
    </Section>
  );
}
