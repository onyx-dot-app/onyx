import React from "react";
import { FiLink } from "react-icons/fi";
import { FetchToolPacket } from "@/app/chat/services/streamingModels";
import { MessageRenderer } from "@/app/chat/message/messageComponents/interfaces";
import { BlinkingDot } from "@/app/chat/message/BlinkingDot";
import { OnyxDocument } from "@/lib/search/interfaces";
import { ValidSources } from "@/lib/types";
import { SearchChipList, SourceInfo } from "../search/SearchChipList";
import { useToolTiming, getMetadataTags } from "../search";
import {
  constructCurrentFetchState,
  INITIAL_URLS_TO_SHOW,
  URLS_PER_EXPANSION,
  READING_MIN_DURATION_MS,
  READ_MIN_DURATION_MS,
} from "./fetchStateUtils";
import Text from "@/refresh-components/texts/Text";

const urlToSourceInfo = (url: string, index: number): SourceInfo => ({
  id: `url-${index}`,
  title: url,
  sourceType: "web",
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

export const FetchToolRenderer: MessageRenderer<FetchToolPacket, {}> = ({
  packets,
  onComplete,
  animate,
  stopPacketSeen,
  children,
}) => {
  const fetchState = constructCurrentFetchState(packets);
  const { urls, documents, hasStarted, isLoading, isComplete } = fetchState;

  useToolTiming({
    hasStarted: isLoading || isComplete,
    isComplete,
    animate,
    stopPacketSeen,
    onComplete,
    activeDurationMs: READING_MIN_DURATION_MS,
    completeDurationMs: READ_MIN_DURATION_MS,
  });

  if (!hasStarted) {
    return children({
      icon: FiLink,
      status: null,
      content: <div />,
    });
  }

  const displayDocuments = documents.length > 0;
  const displayUrls = !displayDocuments && isComplete && urls.length > 0;
  const showLoading = !displayDocuments && !displayUrls;

  return children({
    icon: FiLink,
    status: "Opening URLs:",
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
            emptyState={<BlinkingDot />}
          />
        ) : displayUrls ? (
          <SearchChipList
            items={urls}
            initialCount={INITIAL_URLS_TO_SHOW}
            expansionCount={URLS_PER_EXPANSION}
            getKey={(url: string) => url}
            toSourceInfo={urlToSourceInfo}
            onClick={(url: string) => window.open(url, "_blank")}
            emptyState={<BlinkingDot />}
          />
        ) : (
          <div className="flex flex-wrap gap-x-2 gap-y-2 ml-1">
            <BlinkingDot />
          </div>
        )}

        {(displayDocuments || displayUrls) && (
          <>
            <Text as="p" mainUiMuted text03>
              Reading results:
            </Text>
            {displayDocuments ? (
              <SearchChipList
                items={documents}
                initialCount={INITIAL_URLS_TO_SHOW}
                expansionCount={URLS_PER_EXPANSION}
                getKey={(doc: OnyxDocument) => `reading-${doc.document_id}`}
                toSourceInfo={(doc: OnyxDocument) => documentToSourceInfo(doc)}
                onClick={(doc: OnyxDocument) => {
                  if (doc.link) window.open(doc.link, "_blank");
                }}
                emptyState={<BlinkingDot />}
              />
            ) : (
              <SearchChipList
                items={urls}
                initialCount={INITIAL_URLS_TO_SHOW}
                expansionCount={URLS_PER_EXPANSION}
                getKey={(url: string, index: number) =>
                  `reading-${url}-${index}`
                }
                toSourceInfo={urlToSourceInfo}
                onClick={(url: string) => window.open(url, "_blank")}
                emptyState={<BlinkingDot />}
              />
            )}
          </>
        )}
      </div>
    ),
  });
};
