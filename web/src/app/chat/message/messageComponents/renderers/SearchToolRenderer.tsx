import React from "react";
import { FiSearch, FiGlobe } from "react-icons/fi";
import {
  PacketType,
  ToolPacket,
  ToolStart,
  ToolEnd,
  ToolDelta,
} from "../../../services/streamingModels";
import { MessageRenderer, FullChatState } from "../interfaces";
import { SourceChip2 } from "../../../components/input/ChatInputBar";
import { ResultIcon } from "@/components/chat/sources/SourceCard";
import { truncateString } from "@/lib/utils";
import { OnyxDocument } from "@/lib/search/interfaces";
import { buildFullRenderer } from "./utils/buildFullRenderer";

const constructCurrentSearchState = (
  packets: ToolPacket[]
): {
  query: string | null;
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

  const query = searchStart?.tool_main_description ?? null;

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

  return { query, results, isSearching, isComplete };
};

const ExtendedSearchToolRenderer: MessageRenderer<ToolPacket, {}> = ({
  packets,
}: {
  packets: ToolPacket[];
}) => {
  const { query, results, isSearching, isComplete } =
    constructCurrentSearchState(packets);

  // Don't render anything if search hasn't started
  if (!query) {
    return <div></div>;
  }

  // Unified rendering for both searching and complete states
  return (
    <div className="flex flex-col">
      <div className="text-sm leading-normal flex">
        {isSearching
          ? "Searching through internal documents"
          : "Searched internal documents"}
      </div>
      <div className="flex flex-wrap gap-2 ml-1 mt-1">
        {query && (
          <div
            className={`text-xs text-gray-600 mb-2 ${
              isSearching ? "animate-pulse" : ""
            }`}
          >
            <SourceChip2
              icon={<FiSearch size={10} />}
              title={truncateString(query, 30)}
            />
          </div>
        )}
      </div>
      <div className="flex flex-wrap gap-2 ml-1">
        {results.slice(0, 3).map((result, index) => (
          <div
            key={result.document_id}
            className="animate-in fade-in slide-in-from-bottom-1 duration-300"
            style={{ animationDelay: `${index * 100}ms` }}
          >
            <SourceChip2
              icon={<ResultIcon doc={result} size={10} />}
              title={result.semantic_identifier || ""}
              onClick={() => {
                window.open(result.link, "_blank");
              }}
            />
          </div>
        ))}
      </div>
    </div>
  );
};

const SearchToolRenderer: MessageRenderer<ToolPacket, {}> = ({
  packets,
}: {
  packets: ToolPacket[];
}) => {
  const { query, results, isSearching, isComplete } =
    constructCurrentSearchState(packets);

  if (isSearching) {
    return (
      <div className="text-sm text-muted-foreground">
        Searching for: "{query}"...
      </div>
    );
  }

  if (isComplete && results.length > 0) {
    return (
      <div className="text-sm text-muted-foreground">
        Found {results.length} result{results.length > 1 ? "s" : ""} for "
        {query}"
      </div>
    );
  }

  if (isComplete && results.length === 0) {
    return (
      <div className="text-sm text-muted-foreground">
        No results found for "{query}"
      </div>
    );
  }

  return <div className="text-sm text-muted-foreground">Search: "{query}"</div>;
};

export const SearchToolFullRenderer = buildFullRenderer(
  FiSearch,
  ExtendedSearchToolRenderer,
  SearchToolRenderer
);
