import React, { useEffect, useState, useRef, useMemo } from "react";
import { FiSearch, FiGlobe } from "react-icons/fi";
import {
  PacketType,
  SearchToolPacket,
  SearchToolStart,
  SearchToolDelta,
  SectionEnd,
} from "../../../services/streamingModels";
import { MessageRenderer } from "../interfaces";
import { ResultIcon } from "@/components/chat/sources/SourceCard";
import { OnyxDocument } from "@/lib/search/interfaces";
import { SourceChip2 } from "@/app/chat/components/SourceChip2";
import { BlinkingDot } from "../../BlinkingDot";
import Text from "@/refresh-components/texts/Text";
import { SearchToolRendererV2 } from "./SearchToolRendererV2";
import { usePostHog } from "posthog-js/react";
import { ResearchType } from "@/app/chat/interfaces";

const INITIAL_RESULTS_TO_SHOW = 3;
const RESULTS_PER_EXPANSION = 10;

const INITIAL_QUERIES_TO_SHOW = 3;
const QUERIES_PER_EXPANSION = 5;

const SEARCHING_MIN_DURATION_MS = 1000; // 1 second minimum for "Searching" state
const SEARCHED_MIN_DURATION_MS = 1000; // 1 second minimum for "Searched" state

const constructCurrentSearchState = (
  packets: SearchToolPacket[]
): {
  queries: string[];
  results: OnyxDocument[];
  isSearching: boolean;
  isComplete: boolean;
  isInternetSearch: boolean;
} => {
  // Check for new specific search tool packets first
  const searchStart = packets.find(
    (packet) => packet.obj.type === PacketType.SEARCH_TOOL_START
  )?.obj as SearchToolStart | null;
  const searchDeltas = packets
    .filter((packet) => packet.obj.type === PacketType.SEARCH_TOOL_DELTA)
    .map((packet) => packet.obj as SearchToolDelta);
  const searchEnd = packets.find(
    (packet) => packet.obj.type === PacketType.SECTION_END
  )?.obj as SectionEnd | null;

  // Extract queries from ToolDelta packets
  const queries = searchDeltas
    .flatMap((delta) => delta?.queries || [])
    .filter((query, index, arr) => arr.indexOf(query) === index); // Remove duplicates

  const seenDocIds = new Set<string>();
  const results = searchDeltas
    .flatMap((delta) => delta?.documents || [])
    .filter((doc) => {
      if (!doc || !doc.document_id) return false;
      if (seenDocIds.has(doc.document_id)) return false;
      seenDocIds.add(doc.document_id);
      return true;
    });

  const isSearching = Boolean(searchStart && !searchEnd);
  const isComplete = Boolean(searchStart && searchEnd);
  const isInternetSearch = searchStart?.is_internet_search || false;

  return { queries, results, isSearching, isComplete, isInternetSearch };
};

export const SearchToolRenderer: MessageRenderer<
  SearchToolPacket,
  { researchType?: string | null }
> = ({
  packets,
  state,
  onComplete,
  renderType,
  animate,
  stopPacketSeen,
  children,
}) => {
  const posthog = usePostHog();
  const isSimpleAgentFrameworkEnabled =
    posthog.isFeatureEnabled("simple-agent-framework") ?? false;
  // Check if this message has a research_type, which indicates it's using the simple agent framework
  const isDeepResearch = state.researchType === ResearchType.Deep;

  // Initialize all hooks at the top level (before any conditional returns)
  const { queries, results, isSearching, isComplete, isInternetSearch } =
    constructCurrentSearchState(packets);

  // Track search timing for minimum display duration
  const [searchStartTime, setSearchStartTime] = useState<number | null>(null);
  const [shouldShowAsSearching, setShouldShowAsSearching] = useState(false);

  const [shouldShowAsSearched, setShouldShowAsSearched] = useState(isComplete);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const searchedTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const completionHandledRef = useRef(false);

  // Track how many results to show
  const [resultsToShow, setResultsToShow] = useState(INITIAL_RESULTS_TO_SHOW);

  // Track how many queries to show
  const [queriesToShow, setQueriesToShow] = useState(INITIAL_QUERIES_TO_SHOW);

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
  }, [isComplete, searchStartTime, animate, queries, onComplete]);

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
    const searchType = isInternetSearch ? "the web" : "internal documents";

    // If we have documents to show and we're in the searched state, show "Searched"
    if (results.length > 0) {
      // If we're still showing as searching (before transition), show "Searching"
      if (shouldShowAsSearching) {
        return `Searching ${searchType}`;
      }
      // Otherwise show "Searched"
      return `Searched ${searchType}`;
    }

    // Handle states based on timing
    if (shouldShowAsSearched) {
      return `Searched ${searchType}`;
    }
    if (isSearching || isComplete || shouldShowAsSearching) {
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
  const icon = isInternetSearch ? FiGlobe : FiSearch;

  // If this message has a research type, use the V2 renderer (simple agent framework)
  if (isSimpleAgentFrameworkEnabled && !isDeepResearch) {
    return (
      <SearchToolRendererV2
        packets={packets}
        state={state}
        onComplete={onComplete}
        renderType={renderType}
        animate={animate}
        stopPacketSeen={stopPacketSeen}
      >
        {children}
      </SearchToolRendererV2>
    );
  }

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
      <div className="flex flex-col py-padding-button gap-spacing-interline">
        <Text text02 secondaryBody>
          Queries
        </Text>
        <div className="flex flex-wrap gap-spacing-interline pl-1">
          {queries.slice(0, queriesToShow).map((query, index) => (
            <div
              key={index}
              className="animate-in fade-in slide-in-from-left-2 duration-150"
              style={{
                animationDelay: `${index * 30}ms`,
                animationFillMode: "backwards",
              }}
            >
              <SourceChip2 icon={<FiSearch size={10} />} title={query} />
            </div>
          ))}
          {/* Show a blurb if there are more queries than we are displaying */}
          {queries.length > queriesToShow && (
            <div
              className="animate-in fade-in slide-in-from-left-2 duration-150"
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

        <Text text02 secondaryBody>
          {isInternetSearch ? "Results" : "Documents"}
        </Text>

        <div className="flex flex-wrap gap-2 ml-1">
          {results.slice(0, resultsToShow).map((result, index) => (
            <div
              key={result.document_id}
              className="animate-in fade-in slide-in-from-left-2 duration-150"
              style={{
                animationDelay: `${index * 30}ms`,
                animationFillMode: "backwards",
              }}
            >
              <div className="text-xs">
                <SourceChip2
                  icon={<ResultIcon doc={result} size={10} />}
                  title={result.semantic_identifier || ""}
                  onClick={() => {
                    if (result.link) {
                      window.open(result.link, "_blank");
                    }
                  }}
                />
              </div>
            </div>
          ))}
          {/* Show a blurb if there are more results than we are displaying */}
          {results.length > resultsToShow && (
            <div
              className="animate-in fade-in slide-in-from-left-2 duration-150"
              style={{
                animationDelay: `${
                  Math.min(resultsToShow, results.length) * 30
                }ms`,
                animationFillMode: "backwards",
              }}
            >
              <div className="text-xs">
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
            </div>
          )}

          {/* If no results, and queries are showing, show a loading state */}
          {results.length === 0 && queries.length > 0 && <BlinkingDot />}
        </div>
      </div>
    ),
  });
};
