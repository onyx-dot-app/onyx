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
} from "@/lib/timeline/chat/message/messageComponents/types";
import { Text } from "@opal/components";
import { SvgServer } from "@opal/icons";
import { OnyxDocument } from "@/lib/search/types";
import { ValidSources } from "@/lib/connectors/types/source";
import { getSourceDisplayName } from "@/lib/connectors/utils";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { HierarchyNodeSearchSummary } from "@/lib/hierarchy/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { SourceInfo } from "@/lib/timeline/components/bodies/SearchChipList";
import { RetrievalBody } from "@/lib/timeline/components/bodies/RetrievalBody";
import {
  postgresQueryChips,
  postgresQueryFolderId,
} from "./postgresQueryChips";

// A query has a handful of parts; show them all.
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
 * PostgresToolRenderer - Renders knowledge-base metadata query steps as
 * internal search renders its steps (`RetrievalBody`): the query's parts,
 * then the documents read.
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
  // A count (or a count grouped by a field) answers with a number.
  const query = start?.query ?? {};
  const listsDocuments =
    !(query.count === true || query.count === "true") && !query.group_by;
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
      supportsCollapsible: true,
      timelineLayout: "timeline",
      // The same body as internal search: the query's parts, then the
      // documents read, with a shimmer until they arrive. Nothing to open
      // until the query arrives.
      content:
        chips.length === 0 && documents.length === 0 ? null : (
          <RetrievalBody
            queries={chips.map((chip) => chip.label)}
            // A count returns a number, not documents: it has no
            // "Documents read" section, so no shimmer and no empty state.
            results={
              listsDocuments ? documents.map(documentToSourceInfo) : null
            }
            isComplete={isComplete}
          />
        ),
    },
  ]);
};
