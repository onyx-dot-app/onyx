import React, { useEffect, useState, useRef, useMemo } from "react";
import { FiSearch, FiGlobe } from "react-icons/fi";
import {
  PacketType,
  ToolPacket,
  ToolStart,
  ToolEnd,
  ToolDelta,
} from "../../../services/streamingModels";
import { MessageRenderer, RenderType } from "../interfaces";
import { SourceChip2 } from "../../../components/input/ChatInputBar";
import { ResultIcon } from "@/components/chat/sources/SourceCard";
import { truncateString } from "@/lib/utils";
import { OnyxDocument } from "@/lib/search/interfaces";

const MAX_RESULTS_TO_SHOW = 3;
const MAX_TITLE_LENGTH = 25;

const SEARCHING_MIN_DURATION_MS = 500;

const constructCurrentSearchState = (
  packets: ToolPacket[]
): {
  queries: string[];
  results: OnyxDocument[];
  isSearching: boolean;
  isComplete: boolean;
} => {
  const searchStart = packets.find(
    (packet) => packet.obj.type === PacketType.TOOL_START
  )?.obj as ToolStart | null;
  const searchDeltas = packets
    .filter((packet) => packet.obj.type === PacketType.TOOL_DELTA)
    .map((packet) => packet.obj as ToolDelta);
  const searchEnd = packets.find(
    (packet) => packet.obj.type === PacketType.TOOL_END
  )?.obj as ToolEnd | null;

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

  return { queries, results, isSearching, isComplete };
};

export const SearchToolRenderer: MessageRenderer<ToolPacket, {}> = ({
  packets,
  onComplete,
  renderType,
  animate,
}) => {
  const { queries, results, isSearching, isComplete } =
    constructCurrentSearchState(packets);

  // Track search timing for minimum display duration
  const [searchStartTime, setSearchStartTime] = useState<number | null>(null);
  const [shouldShowAsSearching, setShouldShowAsSearching] = useState(false);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const completionHandledRef = useRef(false);

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
      const minimumDuration = animate ? SEARCHING_MIN_DURATION_MS : 0;

      const handleCompletion = () => {
        setShouldShowAsSearching(false);
        console.log(
          `Complete for search tool with queries: ${queries.join(", ")}`
        );
        onComplete();
      };

      if (elapsedTime >= minimumDuration) {
        // Enough time has passed, show completed state immediately
        handleCompletion();
      } else {
        // Not enough time has passed, delay the completion
        const remainingTime = minimumDuration - elapsedTime;
        timeoutRef.current = setTimeout(handleCompletion, remainingTime);
      }
    }
  }, [isComplete, searchStartTime, animate, queries, onComplete]);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  const status = useMemo(() => {
    if (isComplete) {
      return "Searched internal documents";
    }
    if (isSearching || isComplete) {
      return "Searching internal documents";
    }
    return null;
  }, [isSearching, isComplete]);

  // Don't render anything if search hasn't started
  if (queries.length === 0) {
    return {
      icon: FiSearch,
      status: null,
      content: <div></div>,
    };
  }

  return {
    icon: FiSearch,
    status,
    content: (
      <div className="flex flex-col">
        <div className="flex flex-col">
          <div className="flex flex-wrap gap-2 ml-1 mt-1">
            {queries.map((query, index) => (
              <div key={index} className={`text-xs text-gray-600 mb-2`}>
                <SourceChip2
                  icon={<FiSearch size={10} />}
                  title={truncateString(query, MAX_TITLE_LENGTH)}
                />
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-2 ml-1">
            {results.slice(0, MAX_RESULTS_TO_SHOW).map((result, index) => (
              <div
                key={result.document_id}
                className="animate-in fade-in slide-in-from-bottom-1 duration-300"
                style={{ animationDelay: `${index * 100}ms` }}
              >
                <SourceChip2
                  icon={<ResultIcon doc={result} size={10} />}
                  title={truncateString(
                    result.semantic_identifier || "",
                    MAX_TITLE_LENGTH
                  )}
                  onClick={() => {
                    window.open(result.link, "_blank");
                  }}
                />
              </div>
            ))}
            {/* Show a blurb if there are more results than we are displaying */}
            {results.length > MAX_RESULTS_TO_SHOW && (
              <div
                className="animate-in fade-in slide-in-from-bottom-1 duration-300"
                style={{
                  animationDelay: `${MAX_RESULTS_TO_SHOW * 100}ms`,
                }}
              >
                <SourceChip2
                  title={`${results.length - MAX_RESULTS_TO_SHOW} more...`}
                />
              </div>
            )}
          </div>
        </div>
      </div>
    ),
  };
};
