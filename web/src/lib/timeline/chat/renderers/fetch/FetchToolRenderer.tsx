import { useTranslations } from "next-intl";
import { RetrievalBody } from "@/lib/timeline/components/bodies/RetrievalBody";
import { FetchToolPacket } from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/types";
import { OnyxDocument } from "@/lib/search/types";
import { openExternalLink } from "@/lib/search/utils";
import { ValidSources } from "@/lib/connectors/types/source";
import {
  SearchChipList,
  SourceInfo,
} from "@/lib/timeline/components/bodies/SearchChipList";
import { getMetadataTags } from "../search/searchStateUtils";
import {
  constructCurrentFetchState,
  INITIAL_URLS_TO_SHOW,
  URLS_PER_EXPANSION,
} from "./fetchStateUtils";
import { Text } from "@opal/components";
import { STEP_ICONS } from "@/lib/timeline/icons";

const urlToSourceInfo = (url: string): SourceInfo => ({
  id: `url-${url}`,
  title: url,
  sourceType: ValidSources.Web,
  sourceUrl: url,
});

const documentToSourceInfo = (doc: OnyxDocument): SourceInfo => ({
  id: doc.document_id,
  title: doc.semantic_identifier || doc.link || "",
  sourceType: doc.source_type || ValidSources.Web,
  sourceUrl: doc.link,
  description: doc.blurb,
  metadata: {
    date: doc.updated_at || undefined,
    tags: getMetadataTags(doc.metadata),
  },
});

/**
 * FetchToolRenderer - Renders URL fetch/open tool execution steps
 *
 * RenderType modes:
 * - FULL: Shows all details (URLs being opened + reading). Header passed as `status` prop.
 *         Used when step is expanded in timeline.
 * - COMPACT: Shows only reading (no URL list). Header passed as `status` prop.
 *            Used when step is collapsed in timeline, still wrapped in RunStep.
 * - HIGHLIGHT: Shows URL list with header embedded directly in content.
 *              No RunStep wrapper. Used for parallel streaming preview.
 */
export const FetchToolRenderer: MessageRenderer<FetchToolPacket, {}> = ({
  packets,
  onComplete,
  animate,
  stopPacketSeen,
  renderType,
  children,
}) => {
  const t = useTranslations("chat.messages.timeline");
  const fetchState = constructCurrentFetchState(packets);
  const { urls, documents, pendingUrls, pageCount, hasStarted } = fetchState;
  // Once done, only the pages it read, so URLs that failed do not count as
  // browsed.
  const readCount = documents.length;
  const isCompact = renderType === RenderType.COMPACT;
  const isHighlight = renderType === RenderType.HIGHLIGHT;

  if (!hasStarted) {
    return children([
      {
        icon: STEP_ICONS.fetch,
        status: t("fetch.reading.status", { count: pageCount }),
        doneStatus: t("fetch.read.status", { count: readCount }),
        content: <div />,
        supportsCollapsible: false,
        timelineLayout: "timeline",
      },
    ]);
  }

  // The URLs show as soon as the step names them. Each opened page replaces
  // its URL as it opens. A step that opened nothing keeps its URLs.
  const sources: SourceInfo[] =
    documents.length > 0
      ? [
          ...documents.map(documentToSourceInfo),
          ...pendingUrls.map(urlToSourceInfo),
        ]
      : urls.map(urlToSourceInfo);

  // HIGHLIGHT mode: header embedded in content, no RunStep
  if (isHighlight) {
    return children([
      {
        icon: null,
        status: null,
        supportsCollapsible: false,
        timelineLayout: "content",
        content: (
          <div className="flex flex-col">
            <div className="mb-1">
              <Text as="p" color="text-02">
                {t("fetch.reading.status", { count: pageCount })}
              </Text>
            </div>
            {sources.length > 0 && (
              <SearchChipList
                items={sources}
                initialCount={INITIAL_URLS_TO_SHOW}
                expansionCount={URLS_PER_EXPANSION}
                getKey={(source: SourceInfo) => source.id}
                toSourceInfo={(source: SourceInfo) => source}
                onClick={(source: SourceInfo) => {
                  if (source.sourceUrl) openExternalLink(source.sourceUrl);
                }}
              />
            )}
          </div>
        ),
      },
    ]);
  }

  return children([
    {
      icon: STEP_ICONS.fetch,
      status: t("fetch.reading.status", { count: pageCount }),
      doneStatus: t("fetch.read.status", { count: readCount }),
      supportsCollapsible: false,
      timelineLayout: "timeline",
      content: (
        <RetrievalBody
          queries={[]}
          results={sources}
          isComplete={stopPacketSeen}
          compact
        />
      ),
    },
  ]);
};
