import React from "react";
import { FiGlobe, FiLink } from "react-icons/fi";
import { FetchToolPacket } from "@/app/chat/services/streamingModels";
import { MessageRenderer } from "@/app/chat/message/messageComponents/interfaces";
import { BlinkingDot } from "@/app/chat/message/BlinkingDot";
import { OnyxDocument } from "@/lib/search/interfaces";
import { getUniqueIconFactories } from "@/components/chat/sources/SourceCard";
import { IconProps } from "@/components/icons/icons";
import { SearchChipList } from "../search/SearchChipList";
import { useToolTiming, useExpandableList } from "../search";
import {
  constructCurrentFetchState,
  INITIAL_URLS_TO_SHOW,
  URLS_PER_EXPANSION,
  READING_MIN_DURATION_MS,
  READ_MIN_DURATION_MS,
} from "./fetchStateUtils";

/**
 * Main renderer for fetch tool packets.
 * Handles URL fetching with timing, animations, and visual feedback.
 */
export const FetchToolRenderer: MessageRenderer<FetchToolPacket, {}> = ({
  packets,
  onComplete,
  animate,
  stopPacketSeen,
  children,
}) => {
  const fetchState = constructCurrentFetchState(packets);
  const { urls, documents, hasStarted, isLoading, isComplete } = fetchState;

  // Use timing hook for minimum display durations
  useToolTiming({
    hasStarted: isLoading || isComplete,
    isComplete,
    animate,
    stopPacketSeen,
    onComplete,
    activeDurationMs: READING_MIN_DURATION_MS,
    completeDurationMs: READ_MIN_DURATION_MS,
  });

  // Don't render anything if fetch hasn't started
  if (!hasStarted) {
    return children({
      icon: FiLink,
      status: null,
      content: <div />,
    });
  }

  // Show documents if available, otherwise fall back to URLs
  const displayDocuments = documents.length > 0;
  const displayUrls = !displayDocuments && isComplete && urls.length > 0;
  const showLoading = !displayDocuments && !displayUrls;

  return children({
    icon: FiLink,
    status: "Opening URLs:",
    content: (
      <div className="flex flex-col">
        {/* URLs section */}
        {displayDocuments ? (
          <SearchChipList
            items={documents}
            initialCount={INITIAL_URLS_TO_SHOW}
            expansionCount={URLS_PER_EXPANSION}
            getKey={(doc: OnyxDocument) => doc.document_id}
            getIconFactory={() => (props: IconProps) => (
              <FiGlobe size={props.size} />
            )}
            getTitle={(doc: OnyxDocument) =>
              doc.semantic_identifier || doc.link || ""
            }
            onClick={(doc: OnyxDocument) => {
              if (doc.link) {
                window.open(doc.link, "_blank");
              }
            }}
            getMoreIconFactories={(remaining) =>
              getUniqueIconFactories(remaining)
            }
            emptyState={<BlinkingDot />}
          />
        ) : displayUrls ? (
          <SearchChipList
            items={urls}
            initialCount={INITIAL_URLS_TO_SHOW}
            expansionCount={URLS_PER_EXPANSION}
            getKey={(url: string) => url}
            getIconFactory={() => (props: IconProps) => (
              <FiGlobe size={props.size} />
            )}
            getTitle={(url: string) => url}
            onClick={(url: string) => {
              window.open(url, "_blank");
            }}
            emptyState={<BlinkingDot />}
          />
        ) : (
          <div className="flex flex-wrap gap-x-2 gap-y-2 ml-1">
            <BlinkingDot />
          </div>
        )}

        {/* Reading results section */}
        {(displayDocuments || displayUrls) && (
          <>
            <div className="text-sm text-text-500 mt-3 mb-1">
              Reading results:
            </div>
            <SearchChipList
              items={
                displayDocuments ? documents : urls.map((url) => ({ url }))
              }
              initialCount={INITIAL_URLS_TO_SHOW}
              expansionCount={URLS_PER_EXPANSION}
              getKey={(item: any) =>
                displayDocuments ? item.document_id : item.url
              }
              getIconFactory={() => (props: IconProps) => (
                <FiGlobe size={props.size} />
              )}
              getTitle={(item: any) =>
                displayDocuments
                  ? item.semantic_identifier || item.link || ""
                  : item.url
              }
              onClick={(item: any) => {
                const link = displayDocuments ? item.link : item.url;
                if (link) {
                  window.open(link, "_blank");
                }
              }}
              getMoreIconFactories={
                displayDocuments
                  ? (remaining: any) => getUniqueIconFactories(remaining)
                  : undefined
              }
              emptyState={<BlinkingDot />}
            />
          </>
        )}
      </div>
    ),
  });
};
