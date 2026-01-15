import React from "react";
import { SvgSearch, SvgGlobe } from "@opal/icons";
import { SearchToolPacket } from "@/app/chat/services/streamingModels";
import { MessageRenderer } from "@/app/chat/message/messageComponents/interfaces";
import { BlinkingDot } from "@/app/chat/message/BlinkingDot";
import { OnyxDocument } from "@/lib/search/interfaces";
import { ResultIcon } from "@/components/chat/sources/SourceCard";
import { SearchChipList } from "./SearchChipList";
import { useToolTiming } from "./useToolTiming";
import {
  constructCurrentSearchState,
  INITIAL_QUERIES_TO_SHOW,
  QUERIES_PER_EXPANSION,
  INITIAL_RESULTS_TO_SHOW,
  RESULTS_PER_EXPANSION,
} from "./searchStateUtils";

/**
 * Main renderer for search tool packets.
 * Handles both internal search and internet search with appropriate
 * timing, animations, and visual feedback.
 */
export const SearchToolRenderer: MessageRenderer<SearchToolPacket, {}> = ({
  packets,
  onComplete,
  animate,
  stopPacketSeen,
  children,
}) => {
  const searchState = constructCurrentSearchState(packets);
  const { queries, results, isSearching, isComplete, isInternetSearch } =
    searchState;

  // Determine if search has started (even if completed instantly)
  const hasStarted = isSearching || isComplete;

  // Use timing hook for minimum display durations
  useToolTiming({
    hasStarted,
    isComplete,
    animate,
    stopPacketSeen,
    onComplete,
  });

  // Determine icon based on search type
  const icon = isInternetSearch ? SvgGlobe : SvgSearch;

  // Section header text based on search type
  const queriesHeader = isInternetSearch
    ? "Searching the web for:"
    : "Searching internal documents for:";

  // Don't render content if search hasn't started
  if (queries.length === 0) {
    return children({
      icon,
      status: null,
      content: <div />,
    });
  }

  return children({
    icon,
    status: queriesHeader,
    content: (
      <div className="flex flex-col">
        {/* Queries section */}
        <SearchChipList
          items={queries}
          initialCount={INITIAL_QUERIES_TO_SHOW}
          expansionCount={QUERIES_PER_EXPANSION}
          getKey={(_, index) => index}
          getIcon={() => <SvgSearch size={10} />}
          getTitle={(query: string) => query}
          emptyState={<BlinkingDot />}
        />

        {/* Results section - show for both internal and web search */}
        {(results.length > 0 || queries.length > 0) && (
          <>
            <div className="text-sm text-text-500 mt-3 mb-1">
              Reading results:
            </div>
            <SearchChipList
              items={results}
              initialCount={INITIAL_RESULTS_TO_SHOW}
              expansionCount={RESULTS_PER_EXPANSION}
              getKey={(doc: OnyxDocument) => doc.document_id}
              getIcon={(doc: OnyxDocument) => (
                <ResultIcon doc={doc} size={10} />
              )}
              getTitle={(doc: OnyxDocument) => doc.semantic_identifier || ""}
              onClick={(doc: OnyxDocument) => {
                if (doc.link) {
                  window.open(doc.link, "_blank");
                }
              }}
              emptyState={<BlinkingDot />}
            />
          </>
        )}
      </div>
    ),
  });
};
