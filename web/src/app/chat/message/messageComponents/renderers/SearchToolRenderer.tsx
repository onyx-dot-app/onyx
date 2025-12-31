import React, { useEffect, useState, useRef, useMemo, JSX } from "react";
import { SvgSearch, SvgGlobe, SvgBookOpen, SvgXCircle } from "@opal/icons";
import {
  PacketType,
  SearchToolPacket,
  SearchToolStart,
  SearchToolQueriesDelta,
  SearchToolDocumentsDelta,
  SectionEnd,
} from "../../../services/streamingModels";
import { MessageRenderer, RendererResult } from "../interfaces";
import { truncateString } from "@/lib/utils";
import { SourceChip2 } from "@/app/chat/components/SourceChip2";
import { BlinkingDot } from "../../BlinkingDot";
import { OnyxDocument } from "@/lib/search/interfaces";
import { ResultIcon } from "@/components/chat/sources/SourceCard";
import { IconType } from "react-icons";
import { OnyxIconType } from "@/components/icons/icons";

const MAX_TITLE_LENGTH = 25;

const INITIAL_QUERIES_TO_SHOW = 3;
const QUERIES_PER_EXPANSION = 5;

const INITIAL_RESULTS_TO_SHOW = 3;
const RESULTS_PER_EXPANSION = 10;

const SEARCHING_MIN_DURATION_MS = 1000; // 1 second minimum for "Searching" state
const SEARCHED_MIN_DURATION_MS = 1000; // 1 second minimum for "Searched" state

export interface SearchState {
  queries: string[];
  results: OnyxDocument[];
  isSearching: boolean;
  hasResults: boolean;
  isComplete: boolean;
  isInternetSearch: boolean;
}

export const constructCurrentSearchState = (
  packets: SearchToolPacket[]
): SearchState => {
  // Check for new specific search tool packets first
  const searchStart = packets.find(
    (packet) => packet.obj.type === PacketType.SEARCH_TOOL_START
  )?.obj as SearchToolStart | null;

  // Extract queries from SEARCH_TOOL_QUERIES_DELTA packets
  const queryDeltas = packets
    .filter(
      (packet) => packet.obj.type === PacketType.SEARCH_TOOL_QUERIES_DELTA
    )
    .map((packet) => packet.obj as SearchToolQueriesDelta);

  // Extract documents from SEARCH_TOOL_DOCUMENTS_DELTA packets
  const documentDeltas = packets
    .filter(
      (packet) => packet.obj.type === PacketType.SEARCH_TOOL_DOCUMENTS_DELTA
    )
    .map((packet) => packet.obj as SearchToolDocumentsDelta);

  const searchEnd = packets.find(
    (packet) =>
      packet.obj.type === PacketType.SECTION_END ||
      packet.obj.type === PacketType.ERROR
  )?.obj as SectionEnd | null;

  // Extract queries from query delta packets
  const queries = queryDeltas
    .flatMap((delta) => delta?.queries || [])
    .filter((query, index, arr) => arr.indexOf(query) === index); // Remove duplicates

  // Extract documents/results from document delta packets
  const seenDocIds = new Set<string>();
  const results = documentDeltas
    .flatMap((delta) => delta?.documents || [])
    .filter((doc) => {
      if (!doc || !doc.document_id) return false;
      if (seenDocIds.has(doc.document_id)) return false;
      seenDocIds.add(doc.document_id);
      return true;
    });

  const isSearching = Boolean(searchStart && !searchEnd);
  const hasResults = results.length > 0;
  const isComplete = Boolean(searchStart && searchEnd);
  const isInternetSearch = searchStart?.is_internet_search || false;

  return {
    queries,
    results,
    isSearching,
    hasResults,
    isComplete,
    isInternetSearch,
  };
};

// Generic step renderer for search tool steps
function SearchToolStepRenderer<T>({
  packets,
  isActive,
  isCancelled,
  children,
  icon,
  status,
  getItems,
  getChipIcon,
  getChipTitle,
  getChipKey,
  getChipOnClick,
  initialItemsToShow,
  itemsPerExpansion,
}: {
  packets: SearchToolPacket[];
  isActive: boolean;
  isCancelled?: boolean;
  children: (result: RendererResult) => JSX.Element;
  icon: IconType | OnyxIconType;
  status: string;
  getItems: (state: SearchState) => T[];
  getChipIcon: (item: T, index: number) => JSX.Element;
  getChipTitle: (item: T) => string;
  getChipKey: (item: T, index: number) => string | number;
  getChipOnClick?: (item: T) => void;
  initialItemsToShow: number;
  itemsPerExpansion: number;
}) {
  const state = constructCurrentSearchState(packets);
  const items = getItems(state);
  const [itemsToShow, setItemsToShow] = useState(initialItemsToShow);

  return children({
    icon,
    status,
    content: (
      <div className="flex flex-col">
        <div className="flex flex-wrap gap-x-2 gap-y-2 ml-1">
          {items.slice(0, itemsToShow).map((item, index) => (
            <div
              key={getChipKey(item, index)}
              className="text-xs animate-in fade-in slide-in-from-left-2 duration-150"
              style={{
                animationDelay: `${index * 30}ms`,
                animationFillMode: "backwards",
              }}
            >
              <SourceChip2
                icon={getChipIcon(item, index)}
                title={truncateString(getChipTitle(item), MAX_TITLE_LENGTH)}
                onClick={
                  getChipOnClick ? () => getChipOnClick(item) : undefined
                }
              />
            </div>
          ))}
          {items.length > itemsToShow && (
            <div
              className="text-xs animate-in fade-in slide-in-from-left-2 duration-150"
              style={{
                animationDelay: `${Math.min(itemsToShow, items.length) * 30}ms`,
                animationFillMode: "backwards",
              }}
            >
              <SourceChip2
                title={`${items.length - itemsToShow} more...`}
                onClick={() => {
                  setItemsToShow((prevItems) =>
                    Math.min(prevItems + itemsPerExpansion, items.length)
                  );
                }}
              />
            </div>
          )}
          {items.length === 0 &&
            (isCancelled ? (
              <SvgXCircle size={14} className="text-text-400" />
            ) : (
              <BlinkingDot />
            ))}
        </div>
      </div>
    ),
  });
}

// Step 1 Renderer: "Searching internally" with queries
export function SourceRetrievalStepRenderer({
  packets,
  isActive,
  isCancelled,
  children,
}: {
  packets: SearchToolPacket[];
  isActive: boolean;
  isCancelled?: boolean;
  children: (result: RendererResult) => JSX.Element;
}) {
  return (
    <SearchToolStepRenderer
      packets={packets}
      isActive={isActive}
      isCancelled={isCancelled}
      icon={SvgSearch}
      status="Searching internally"
      getItems={(state) => state.queries}
      getChipIcon={() => <SvgSearch size={10} />}
      getChipTitle={(query: string) => query}
      getChipKey={(_, index: number) => index}
      initialItemsToShow={INITIAL_QUERIES_TO_SHOW}
      itemsPerExpansion={QUERIES_PER_EXPANSION}
    >
      {children}
    </SearchToolStepRenderer>
  );
}

// Step 2 Renderer: "Reading" with documents
export function ReadDocumentsStepRenderer({
  packets,
  isActive,
  isCancelled,
  children,
}: {
  packets: SearchToolPacket[];
  isActive: boolean;
  isCancelled?: boolean;
  children: (result: RendererResult) => JSX.Element;
}) {
  return (
    <SearchToolStepRenderer
      packets={packets}
      isActive={isActive}
      isCancelled={isCancelled}
      icon={SvgBookOpen}
      status="Reading"
      getItems={(state) => state.results}
      getChipIcon={(doc: OnyxDocument) => <ResultIcon doc={doc} size={10} />}
      getChipTitle={(doc: OnyxDocument) => doc.semantic_identifier || ""}
      getChipKey={(doc: OnyxDocument) => doc.document_id}
      getChipOnClick={(doc: OnyxDocument) => {
        if (doc.link) {
          window.open(doc.link, "_blank");
        }
      }}
      initialItemsToShow={INITIAL_RESULTS_TO_SHOW}
      itemsPerExpansion={RESULTS_PER_EXPANSION}
    >
      {children}
    </SearchToolStepRenderer>
  );
}

export const SearchToolRenderer: MessageRenderer<SearchToolPacket, {}> = ({
  packets,
  onComplete,
  animate,
  stopPacketSeen,
  children,
}) => {
  const { queries, results, isSearching, isComplete, isInternetSearch } =
    constructCurrentSearchState(packets);

  // Track search timing for minimum display duration
  const [searchStartTime, setSearchStartTime] = useState<number | null>(null);
  const [shouldShowAsSearching, setShouldShowAsSearching] = useState(false);

  const [shouldShowAsSearched, setShouldShowAsSearched] = useState(isComplete);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const searchedTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const completionHandledRef = useRef(false);

  // Track how many queries to show
  const [queriesToShow, setQueriesToShow] = useState(INITIAL_QUERIES_TO_SHOW);

  // Track how many results to show
  const [resultsToShow, setResultsToShow] = useState(INITIAL_RESULTS_TO_SHOW);

  // Track when search starts (even if the search completes instantly)
  useEffect(() => {
    if ((isSearching || isComplete) && searchStartTime === null) {
      setSearchStartTime(Date.now());
      setShouldShowAsSearching(true);
    }
  }, [isSearching, isComplete, searchStartTime]);

  // Handle search completion with minimum duration
  useEffect(() => {
    if (
      isComplete &&
      searchStartTime !== null &&
      !completionHandledRef.current
    ) {
      completionHandledRef.current = true;

      // If stopped, skip intermediate states and complete immediately
      if (stopPacketSeen) {
        // Clear any pending timeouts
        if (timeoutRef.current) {
          clearTimeout(timeoutRef.current);
        }
        if (searchedTimeoutRef.current) {
          clearTimeout(searchedTimeoutRef.current);
        }

        // Skip "Searched" state, go directly to completion
        setShouldShowAsSearching(false);
        setShouldShowAsSearched(false);
        onComplete();
        return;
      }

      const elapsedTime = Date.now() - searchStartTime;
      const minimumSearchingDuration = animate ? SEARCHING_MIN_DURATION_MS : 0;
      const minimumSearchedDuration = animate ? SEARCHED_MIN_DURATION_MS : 0;

      const handleSearchingToSearched = () => {
        setShouldShowAsSearching(false);
        setShouldShowAsSearched(true);

        searchedTimeoutRef.current = setTimeout(() => {
          setShouldShowAsSearched(false);
          onComplete();
        }, minimumSearchedDuration);
      };

      if (elapsedTime >= minimumSearchingDuration) {
        // Enough time has passed for searching, transition to searched immediately
        handleSearchingToSearched();
      } else {
        // Not enough time has passed for searching, delay the transition
        const remainingTime = minimumSearchingDuration - elapsedTime;
        timeoutRef.current = setTimeout(
          handleSearchingToSearched,
          remainingTime
        );
      }
    }
  }, [
    isComplete,
    searchStartTime,
    animate,
    queries,
    onComplete,
    stopPacketSeen,
  ]);

  // Cleanup timeouts when stopped
  useEffect(() => {
    if (stopPacketSeen) {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
      if (searchedTimeoutRef.current) {
        clearTimeout(searchedTimeoutRef.current);
        searchedTimeoutRef.current = null;
      }
      // Reset states to prevent flickering
      setShouldShowAsSearching(false);
      setShouldShowAsSearched(false);
    }
  }, [stopPacketSeen]);

  // Cleanup timeouts on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
      if (searchedTimeoutRef.current) {
        clearTimeout(searchedTimeoutRef.current);
      }
    };
  }, []);

  const status = useMemo(() => {
    const searchType = isInternetSearch ? "online" : "internally";

    // Always use present continuous form
    if (
      isSearching ||
      isComplete ||
      shouldShowAsSearching ||
      shouldShowAsSearched ||
      results.length > 0
    ) {
      return `Searching ${searchType}`;
    }
    return null;
  }, [
    isSearching,
    isComplete,
    shouldShowAsSearching,
    shouldShowAsSearched,
    results.length,
    isInternetSearch,
  ]);

  // Determine the icon based on search type
  const icon = isInternetSearch ? SvgGlobe : SvgSearch;

  // Don't render anything if search hasn't started
  if (queries.length === 0) {
    return children({
      icon,
      status: status,
      content: <div></div>,
    });
  }

  return children({
    icon,
    status,
    content: (
      <div className="flex flex-col mt-1.5">
        <div className="flex flex-col">
          <div className="flex flex-wrap gap-x-2 gap-y-2 ml-1">
            {queries.slice(0, queriesToShow).map((query, index) => (
              <div
                key={index}
                className="text-xs animate-in fade-in slide-in-from-left-2 duration-150"
                style={{
                  animationDelay: `${index * 30}ms`,
                  animationFillMode: "backwards",
                }}
              >
                <SourceChip2
                  icon={<SvgSearch size={10} />}
                  title={truncateString(query, MAX_TITLE_LENGTH)}
                />
              </div>
            ))}
            {/* Show a blurb if there are more queries than we are displaying */}
            {queries.length > queriesToShow && (
              <div
                className="text-xs animate-in fade-in slide-in-from-left-2 duration-150"
                style={{
                  animationDelay: `${queriesToShow * 30}ms`,
                  animationFillMode: "backwards",
                }}
              >
                <SourceChip2
                  title={`${queries.length - queriesToShow} more...`}
                  onClick={() => {
                    setQueriesToShow((prevQueries) =>
                      Math.min(
                        prevQueries + QUERIES_PER_EXPANSION,
                        queries.length
                      )
                    );
                  }}
                />
              </div>
            )}
          </div>

          {/* If no queries, show a loading state */}
          {queries.length === 0 && <BlinkingDot />}
        </div>

        {/* Only show results section for internal search, not web search */}
        {!isInternetSearch && (
          <div className="flex flex-col mt-3">
            <div className="flex flex-wrap gap-x-2 gap-y-2 ml-1">
              {results.slice(0, resultsToShow).map((result, index) => (
                <div
                  key={result.document_id}
                  className="text-xs animate-in fade-in slide-in-from-left-2 duration-150"
                  style={{
                    animationDelay: `${index * 30}ms`,
                    animationFillMode: "backwards",
                  }}
                >
                  <SourceChip2
                    icon={<ResultIcon doc={result} size={10} />}
                    title={truncateString(
                      result.semantic_identifier || "",
                      MAX_TITLE_LENGTH
                    )}
                    onClick={() => {
                      if (result.link) {
                        window.open(result.link, "_blank");
                      }
                    }}
                  />
                </div>
              ))}
              {/* Show a blurb if there are more results than we are displaying */}
              {results.length > resultsToShow && (
                <div
                  className="text-xs animate-in fade-in slide-in-from-left-2 duration-150"
                  style={{
                    animationDelay: `${
                      Math.min(resultsToShow, results.length) * 30
                    }ms`,
                    animationFillMode: "backwards",
                  }}
                >
                  <SourceChip2
                    title={`${results.length - resultsToShow} more...`}
                    onClick={() => {
                      setResultsToShow((prevResults) =>
                        Math.min(
                          prevResults + RESULTS_PER_EXPANSION,
                          results.length
                        )
                      );
                    }}
                  />
                </div>
              )}

              {/* If no results, and queries are showing, show a loading state */}
              {results.length === 0 && queries.length > 0 && <BlinkingDot />}
            </div>
          </div>
        )}
      </div>
    ),
  });
};
