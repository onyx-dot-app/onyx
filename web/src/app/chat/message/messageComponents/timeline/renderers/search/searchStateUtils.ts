import {
  PacketType,
  SearchToolPacket,
  SearchToolStart,
  SearchToolQueriesDelta,
  SearchToolDocumentsDelta,
  SectionEnd,
} from "@/app/chat/services/streamingModels";
import { OnyxDocument } from "@/lib/search/interfaces";

export const MAX_TITLE_LENGTH = 25;

export const getMetadataTags = (metadata?: {
  [key: string]: string;
}): string[] | undefined => {
  if (!metadata) return undefined;
  const tags = Object.values(metadata)
    .filter((value) => typeof value === "string" && value.length > 0)
    .slice(0, 2)
    .map((value) => `# ${value}`);
  return tags.length > 0 ? tags : undefined;
};

export const INITIAL_QUERIES_TO_SHOW = 3;
export const QUERIES_PER_EXPANSION = 5;
export const INITIAL_RESULTS_TO_SHOW = 3;
export const RESULTS_PER_EXPANSION = 10;

export interface SearchState {
  queries: string[];
  results: OnyxDocument[];
  isSearching: boolean;
  hasResults: boolean;
  isComplete: boolean;
  isInternetSearch: boolean;
}

/** Constructs the current search state from search tool packets. */
export const constructCurrentSearchState = (
  packets: SearchToolPacket[]
): SearchState => {
  const searchStart = packets.find(
    (packet) => packet.obj.type === PacketType.SEARCH_TOOL_START
  )?.obj as SearchToolStart | null;

  const queryDeltas = packets
    .filter(
      (packet) => packet.obj.type === PacketType.SEARCH_TOOL_QUERIES_DELTA
    )
    .map((packet) => packet.obj as SearchToolQueriesDelta);

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

  // Deduplicate queries using Set for O(n) instead of indexOf which is O(n²)
  const seenQueries = new Set<string>();
  const queries = queryDeltas
    .flatMap((delta) => delta?.queries || [])
    .filter((query) => {
      if (seenQueries.has(query)) return false;
      seenQueries.add(query);
      return true;
    });

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
