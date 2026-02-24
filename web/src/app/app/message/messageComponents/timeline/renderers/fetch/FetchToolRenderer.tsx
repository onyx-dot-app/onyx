import { FetchToolPacket } from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/interfaces";
import { BlinkingBar } from "@/app/app/message/BlinkingBar";
import { OnyxDocument } from "@/lib/search/interfaces";
import { ValidSources } from "@/lib/types";
import { SearchChipList, SourceInfo } from "../search/SearchChipList";
import { getMetadataTags } from "../search/searchStateUtils";
import {
  constructCurrentFetchState,
  INITIAL_URLS_TO_SHOW,
  URLS_PER_EXPANSION,
} from "./fetchStateUtils";
import Text from "@/refresh-components/texts/Text";
import { SvgCircle } from "@opal/icons";

const urlToSourceInfo = (url: string, index: number): SourceInfo => ({
  id: `url-${index}`,
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
 *            Used when step is collapsed in timeline, still wrapped in StepContainer.
 * - HIGHLIGHT: Shows URL list with header embedded directly in content.
 *              No StepContainer wrapper. Used for parallel streaming preview.
 */
export const FetchToolRenderer: MessageRenderer<FetchToolPacket, {}> = ({
  packets,
  onComplete,
  animate,
  stopPacketSeen,
  renderType,
  children,
}) => {
  const fetchState = constructCurrentFetchState(packets);
  const { urls, documents, hasStarted, isLoading, isComplete } = fetchState;
  const isCompact = renderType === RenderType.COMPACT;
  const isHighlight = renderType === RenderType.HIGHLIGHT;

  if (!hasStarted) {
    return children([
      {
        icon: SvgCircle,
        status: null,
        content: <div />,
        supportsCollapsible: false,
        timelineLayout: "timeline",
      },
    ]);
  }

  const displayDocuments = documents.length > 0;
  const displayUrls = !displayDocuments && isComplete && urls.length > 0;

  // HIGHLIGHT mode: header embedded in content, no StepContainer
  if (isHighlight) {
    return children([
      {
        icon: null,
        status: null,
        supportsCollapsible: false,
        timelineLayout: "content",
        content: (
          <div className="flex flex-col">
            <Text as="p" text02 className="text-sm mb-1">
              Reading
            </Text>
            {displayDocuments ? (
              <SearchChipList
                items={documents}
                initialCount={INITIAL_URLS_TO_SHOW}
                expansionCount={URLS_PER_EXPANSION}
                getKey={(doc: OnyxDocument) => doc.document_id}
                toSourceInfo={(doc: OnyxDocument) => documentToSourceInfo(doc)}
                onClick={(doc: OnyxDocument) => {
                  if (doc.link) window.open(doc.link, "_blank");
                }}
                emptyState={!stopPacketSeen ? <BlinkingBar /> : undefined}
              />
            ) : displayUrls ? (
              <SearchChipList
                items={urls}
                initialCount={INITIAL_URLS_TO_SHOW}
                expansionCount={URLS_PER_EXPANSION}
                getKey={(url: string) => url}
                toSourceInfo={urlToSourceInfo}
                onClick={(url: string) => window.open(url, "_blank")}
                emptyState={!stopPacketSeen ? <BlinkingBar /> : undefined}
              />
            ) : (
              !stopPacketSeen && <BlinkingBar />
            )}
          </div>
        ),
      },
    ]);
  }

  return children([
    {
      icon: SvgCircle,
      status: "Reading",
      supportsCollapsible: false,
      timelineLayout: "timeline",
      content: (
        <div className="flex flex-col">
          {displayDocuments ? (
            <SearchChipList
              items={documents}
              initialCount={INITIAL_URLS_TO_SHOW}
              expansionCount={URLS_PER_EXPANSION}
              getKey={(doc: OnyxDocument) => doc.document_id}
              toSourceInfo={(doc: OnyxDocument) => documentToSourceInfo(doc)}
              onClick={(doc: OnyxDocument) => {
                if (doc.link) window.open(doc.link, "_blank");
              }}
              emptyState={!stopPacketSeen ? <BlinkingBar /> : undefined}
            />
          ) : displayUrls ? (
            <SearchChipList
              items={urls}
              initialCount={INITIAL_URLS_TO_SHOW}
              expansionCount={URLS_PER_EXPANSION}
              getKey={(url: string) => url}
              toSourceInfo={urlToSourceInfo}
              onClick={(url: string) => window.open(url, "_blank")}
              emptyState={!stopPacketSeen ? <BlinkingBar /> : undefined}
            />
          ) : (
            <div className="flex flex-wrap gap-x-2 gap-y-2 ml-1">
              {!stopPacketSeen && <BlinkingBar />}
            </div>
          )}
        </div>
      ),
    },
  ]);
};
