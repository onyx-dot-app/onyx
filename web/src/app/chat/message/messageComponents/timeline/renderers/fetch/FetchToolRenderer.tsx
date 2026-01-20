import React from "react";
import { FiLink } from "react-icons/fi";
import { FetchToolPacket } from "@/app/chat/services/streamingModels";
import {
  MessageRenderer,
  RenderType,
} from "@/app/chat/message/messageComponents/interfaces";
import { BlinkingDot } from "@/app/chat/message/BlinkingDot";
import { OnyxDocument } from "@/lib/search/interfaces";
import { ValidSources } from "@/lib/types";
import { SearchChipList, SourceInfo } from "../search/SearchChipList";
import { getMetadataTags } from "../search";
import {
  constructCurrentFetchState,
  INITIAL_URLS_TO_SHOW,
  URLS_PER_EXPANSION,
} from "./fetchStateUtils";
import Text from "@/refresh-components/texts/Text";

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

  if (!hasStarted) {
    return children({
      icon: FiLink,
      status: null,
      content: <div />,
      supportsCompact: true,
    });
  }

  const displayDocuments = documents.length > 0;
  const displayUrls = !displayDocuments && isComplete && urls.length > 0;

  return children({
    icon: FiLink,
    status: "Opening URLs:",
    supportsCompact: true,
    content: (
      <div className="flex flex-col">
        {!isCompact &&
          (displayDocuments ? (
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
          ))}

        {(displayDocuments || displayUrls) && (
          <>
            {!isCompact && (
              <Text as="p" mainUiMuted text03>
                Reading results:
              </Text>
            )}
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
