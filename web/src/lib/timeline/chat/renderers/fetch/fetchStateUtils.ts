import {
  PacketType,
  FetchToolPacket,
  FetchToolUrls,
} from "@/app/app/services/streamingModels";
import { OnyxDocument } from "@/lib/search/types";

export const INITIAL_URLS_TO_SHOW = 3;
export const URLS_PER_EXPANSION = 5;
export const READING_MIN_DURATION_MS = 1000;
export const READ_MIN_DURATION_MS = 1000;

export interface FetchState {
  urls: string[];
  /** The opened pages so far, in the order they opened. */
  documents: OnyxDocument[];
  /** While the step runs, the URLs that have not opened yet. */
  pendingUrls: string[];
  /** The pages the step browses: the opened ones once it has finished. */
  pageCount: number;
  hasStarted: boolean;
  isLoading: boolean;
  isComplete: boolean;
}

/** A URL without its query, fragment or trailing slash, as the backend
 * names a crawled page. */
function pageKey(url: string): string {
  try {
    const parsed = new URL(url);
    return `${parsed.host}${parsed.pathname.replace(/\/+$/, "")}`;
  } catch {
    return url;
  }
}

/** Constructs the current fetch state from fetch tool packets. The pages
 * arrive one packet at a time, as each one opens. */
export const constructCurrentFetchState = (
  packets: FetchToolPacket[]
): FetchState => {
  const startPacket = packets.find(
    (packet) => packet.obj.type === PacketType.FETCH_TOOL_START
  );
  const urlsPacket = packets.find(
    (packet) => packet.obj.type === PacketType.FETCH_TOOL_URLS
  )?.obj as FetchToolUrls | undefined;
  const documentsById = new Map<string, OnyxDocument>();
  for (const { obj } of packets) {
    if (obj.type !== PacketType.FETCH_TOOL_DOCUMENTS) continue;
    for (const doc of obj.documents) {
      documentsById.set(doc.document_id, doc);
    }
  }
  const sectionEnd = packets.find(
    (packet) =>
      packet.obj.type === PacketType.SECTION_END ||
      packet.obj.type === PacketType.ERROR
  );

  const urls = urlsPacket?.urls || [];
  const documents = [...documentsById.values()];
  const hasStarted = Boolean(startPacket);
  const isComplete = Boolean(startPacket && sectionEnd);
  const isLoading = hasStarted && !isComplete;
  const openedKeys = new Set(
    documents.flatMap((doc) => (doc.link ? [pageKey(doc.link)] : []))
  );
  const pendingUrls = isComplete
    ? []
    : urls.filter((url) => !openedKeys.has(pageKey(url)));
  const pageCount = isComplete
    ? documents.length || urls.length
    : urls.length || documents.length;

  return {
    urls,
    documents,
    pendingUrls,
    pageCount,
    hasStarted,
    isLoading,
    isComplete,
  };
};
