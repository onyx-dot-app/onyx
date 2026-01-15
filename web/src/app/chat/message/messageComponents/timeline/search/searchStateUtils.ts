import {
  PacketType,
  SearchToolPacket,
  SearchToolStart,
  SearchToolQueriesDelta,
  SearchToolDocumentsDelta,
  SectionEnd,
} from "@/app/chat/services/streamingModels";
import { OnyxDocument } from "@/lib/search/interfaces";

// Display constants
export const MAX_TITLE_LENGTH = 25;

// Expansion constants
export const INITIAL_QUERIES_TO_SHOW = 3;
export const QUERIES_PER_EXPANSION = 5;
export const INITIAL_RESULTS_TO_SHOW = 3;
export const RESULTS_PER_EXPANSION = 10;

// Timing constants
export const SEARCHING_MIN_DURATION_MS = 1000;
export const SEARCHED_MIN_DURATION_MS = 1000;

export interface SearchState {
  queries: string[];
  results: OnyxDocument[];
  isSearching: boolean;
  hasResults: boolean;
  isComplete: boolean;
  isInternetSearch: boolean;
}

/**
 * Constructs the current search state from a list of search tool packets.
 * This is a pure function with no side effects.
 */
export const constructCurrentSearchState = (
  packets: SearchToolPacket[]
): SearchState => {
  // Find the search start packet
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

  // Find the end packet (either section end or error)
  const searchEnd = packets.find(
    (packet) =>
      packet.obj.type === PacketType.SECTION_END ||
      packet.obj.type === PacketType.ERROR
  )?.obj as SectionEnd | null;

  // Extract and deduplicate queries
  const queries = queryDeltas
    .flatMap((delta) => delta?.queries || [])
    .filter((query, index, arr) => arr.indexOf(query) === index);

  // Extract and deduplicate documents by document_id
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
