"use client";

import { useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import useSWR from "swr";
import {
  Button,
  Card,
  Dropdown,
  FilterButton,
  InputTypeIn,
  MessageCard,
  Pagination,
  Tag,
} from "@opal/components";
import { useDebouncedValue } from "@opal/hooks";
import { Content, IllustrationContent, Section } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import { CardLoader, IconLoader } from "@opal/loaders";
import {
  SvgActivity,
  SvgCheckCircle,
  SvgPauseCircle,
  SvgSettings,
  SvgXOctagon,
} from "@opal/icons";
import { markdown } from "@opal/utils";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  INDEXING_CONNECTOR_STATUSES,
  type IndexingConnectorStatus,
  type IndexingConnectorsResponse,
} from "@/lib/connectors/types";
import { getSourceMetadata } from "@/lib/connectors/utils";
import type { FederatedConnectorStatus } from "@/lib/types";
import {
  SEARCH_DELAY_MS,
  SEARCH_MAX_LENGTH,
} from "@/views/admin/connectors/ConnectorDetailPage/RunsCard";
import ConnectorRow from "@/views/admin/connectors/IndexingStatusPage/ConnectorRow";

const PAGE_SIZE = 20;
const POLL_MS = 30_000;
const LOADER_ROWS = 4;
const ALL = "all";

// The header counts. Scheduled pairs get none.
const COUNT_TAGS = [
  { status: "indexed", icon: SvgCheckCircle, color: "green" },
  { status: "indexing", icon: IconLoader, color: "blue" },
  { status: "failed", icon: SvgXOctagon, color: "red" },
  { status: "paused", icon: SvgPauseCircle, color: "amber" },
] as const;

interface FederatedRowProps {
  connector: FederatedConnectorStatus;
}
/** A federated connector: searched at query time, so it has no runs or documents. */
function FederatedRow({ connector }: FederatedRowProps) {
  const t = useTranslations("admin.indexing.list");
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
        <Content
          icon={getSourceMetadata(connector.source).icon}
          title={connector.name}
          sizePreset="main-ui"
          variant="section"
          tag={{ title: t("federated.tag"), color: "gray" }}
        />
        <Button
          icon={SvgSettings}
          prominence="tertiary"
          size="sm"
          href={`/admin/federated/${connector.id}`}
          tooltip={t("actions.manageFederated")}
          aria-label={t("actions.manageFederated")}
        />
      </Section>
    </Card>
  );
}

/** Every readable connector, searched and filtered by status, with its latest run at a glance. */
export default function ConnectorList() {
  const t = useTranslations("admin.indexing.list");
  const tBadges = useTranslations("admin.status.badges");
  const format = useFormatter();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<IndexingConnectorStatus | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const search = useDebouncedValue(searchInput.trim(), SEARCH_DELAY_MS);
  const [expandedIds, setExpandedIds] = useState<ReadonlySet<number>>(
    () => new Set()
  );

  const { data, error, isLoading } = useSWR<IndexingConnectorsResponse>(
    SWR_KEYS.indexMonitoringConnectors({
      pageNum: page - 1,
      pageSize: PAGE_SIZE,
      q: search,
      status,
    }),
    errorHandlingFetcher,
    { refreshInterval: POLL_MS, keepPreviousData: true }
  );

  function pickStatus(next: IndexingConnectorStatus | null) {
    setStatus(next);
    setPage(1);
  }

  function toggleExpanded(ccPairId: number) {
    setExpandedIds((current) => {
      const next = new Set(current);
      if (!next.delete(ccPairId)) next.add(ccPairId);
      return next;
    });
  }

  const totalItems = data?.total_items ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalItems / PAGE_SIZE));
  // Polling can shrink the list under an open page.
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);
  const filtered = status !== null || search !== "";
  const empty =
    data !== undefined &&
    data.items.length === 0 &&
    data.federated_connectors.length === 0;

  return (
    <Section alignItems="stretch" gap={2} height="fit">
      <Section
        flexDirection="row"
        justifyContent="between"
        alignItems="center"
        gap={2}
        padding={2}
        height="fit"
        wrap
      >
        <Section height="fit" className="min-w-40 flex-1">
          <InputTypeIn
            searchIcon
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
        <Section
          flexDirection="row"
          justifyContent="end"
          alignItems="center"
          gap={1}
          width="fit"
          height="fit"
        >
          <Dropdown>
            <Dropdown.Trigger asChild>
              <FilterButton
                icon={SvgActivity}
                active={status !== null}
                onClear={() => pickStatus(null)}
              >
                {status === null ? t("statusFilter.all") : tBadges(status)}
              </FilterButton>
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
            gap={2}
            padding={1.5}
            width="fit"
            height="fit"
          >
            {COUNT_TAGS.map((tag) => ({
              ...tag,
              count: data?.status_counts[tag.status] ?? 0,
            }))
              .filter(({ count }) => count > 0)
              .map(({ status: counted, icon, color, count }) => (
                <Tag
                  key={counted}
                  icon={icon}
                  title={format.number(count)}
                  tooltip={t(`counts.${counted}`, { count })}
                  color={color}
                />
              ))}
          </Section>
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
          {data?.items.map((row) => (
            <ConnectorRow
              key={row.cc_pair_id}
              row={row}
              expanded={expandedIds.has(row.cc_pair_id)}
              onToggle={() => toggleExpanded(row.cc_pair_id)}
            />
          ))}
          {data?.federated_connectors.map((connector) => (
            <FederatedRow key={connector.id} connector={connector} />
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
