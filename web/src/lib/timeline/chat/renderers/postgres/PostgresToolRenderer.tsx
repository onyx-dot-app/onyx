"use client";

import { useMemo } from "react";
import useSWR from "swr";
import { useLocale, useTranslations } from "next-intl";
import {
  PacketType,
  PostgresToolDocuments,
  PostgresToolPacket,
  PostgresToolStart,
} from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/types";
import { Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgFilter, SvgServer } from "@opal/icons";
import { OnyxDocument } from "@/lib/search/types";
import { ValidSources } from "@/lib/connectors/types/source";
import { getSourceDisplayName } from "@/lib/connectors/utils";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { HierarchyNodeSearchSummary } from "@/lib/hierarchy/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  SearchChipList,
  SourceInfo,
} from "@/lib/timeline/components/bodies/SearchChipList";
import {
  INITIAL_RESULTS_TO_SHOW,
  RESULTS_PER_EXPANSION,
} from "@/lib/timeline/chat/renderers/search/searchStateUtils";
import {
  PostgresQueryChip,
  postgresQueryChips,
  postgresQueryFolderId,
} from "./postgresQueryChips";

// A query has a handful of parts; show them all.
const QUERY_CHIPS_TO_SHOW = 10;

const chipToSourceInfo = (chip: PostgresQueryChip): SourceInfo => ({
  id: chip.key,
  title: chip.label,
  sourceType: ValidSources.Web,
  icon: SvgFilter,
});

const documentToSourceInfo = (doc: OnyxDocument): SourceInfo => ({
  id: doc.document_id,
  title: doc.semantic_identifier || doc.document_id,
  sourceType: doc.source_type,
  sourceUrl: doc.link,
  metadata: { date: doc.updated_at || undefined },
});

function sourceName(source: string): string {
  return getSourceDisplayName(source as ValidSources) ?? source;
}

/**
 * PostgresToolRenderer - Renders knowledge-base metadata query steps: the
 * query's parts as chips, then the documents the step listed.
 */
export const PostgresToolRenderer: MessageRenderer<PostgresToolPacket, {}> = ({
  packets,
  renderType,
  children,
}) => {
  const t = useTranslations("chat.messages.timeline");
  const locale = useLocale();
  const isComplete = packets.some(
    (packet) =>
      packet.obj.type === PacketType.SECTION_END ||
      packet.obj.type === PacketType.ERROR
  );
  const statusLabel = isComplete
    ? t("postgres.queried.status")
    : t("postgres.querying.status");

  const start = packets.find(
    (packet) => packet.obj.type === PacketType.POSTGRES_TOOL_START
  )?.obj as PostgresToolStart | undefined;
  const folderId = postgresQueryFolderId(start?.query ?? {});
  // A folder the user cannot access returns 404, and the chip keeps its id.
  const { data: folder } = useSWR<HierarchyNodeSearchSummary>(
    folderId !== null ? SWR_KEYS.hierarchyNode(folderId) : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
      shouldRetryOnError: false,
    }
  );
  const chips = useMemo(
    () =>
      postgresQueryChips(
        start?.query ?? {},
        (key, values) => t(`postgres.query.${key}`, values),
        locale,
        sourceName,
        folder?.title
      ),
    [start, t, locale, folder?.title]
  );
  const documents = useMemo(
    () =>
      packets.flatMap((packet) =>
        packet.obj.type === PacketType.POSTGRES_TOOL_DOCUMENTS
          ? (packet.obj as PostgresToolDocuments).documents
          : []
      ),
    [packets]
  );

  if (renderType === RenderType.HIGHLIGHT) {
    return children([
      {
        icon: null,
        status: null,
        supportsCollapsible: false,
        timelineLayout: "content",
        content: (
          <Text as="p" font="main-ui-body" color="text-02">
            {statusLabel}
          </Text>
        ),
      },
    ]);
  }

  return children([
    {
      icon: SvgServer,
      status: statusLabel,
      supportsCollapsible: documents.length > 0,
      timelineLayout: "timeline",
      content: (
        <Section gap={0} alignItems="stretch" height="fit">
          {chips.length > 0 && (
            <SearchChipList
              items={chips}
              initialCount={QUERY_CHIPS_TO_SHOW}
              expansionCount={QUERY_CHIPS_TO_SHOW}
              getKey={(chip) => chip.key}
              toSourceInfo={chipToSourceInfo}
              showDetailsCard={false}
              isQuery={true}
            />
          )}
          {documents.length > 0 && (
            <>
              <Text as="p" font="main-ui-muted" color="text-04">
                {t("postgres.listed.label", { count: documents.length })}
              </Text>
              <SearchChipList
                items={documents}
                initialCount={INITIAL_RESULTS_TO_SHOW}
                expansionCount={RESULTS_PER_EXPANSION}
                getKey={(doc, index) => doc.document_id ?? `result-${index}`}
                toSourceInfo={documentToSourceInfo}
                onClick={(doc) => {
                  if (doc.link) {
                    window.open(doc.link, "_blank", "noopener,noreferrer");
                  }
                }}
              />
            </>
          )}
        </Section>
      ),
    },
  ]);
};
