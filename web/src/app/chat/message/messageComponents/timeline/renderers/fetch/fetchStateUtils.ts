import {
  PacketType,
  FetchToolPacket,
  FetchToolUrls,
  FetchToolDocuments,
} from "@/app/chat/services/streamingModels";
import { OnyxDocument } from "@/lib/search/interfaces";

export const INITIAL_URLS_TO_SHOW = 3;
export const URLS_PER_EXPANSION = 5;
export const READING_MIN_DURATION_MS = 1000;
export const READ_MIN_DURATION_MS = 1000;

export interface FetchState {
  urls: string[];
  documents: OnyxDocument[];
  hasStarted: boolean;
  isLoading: boolean;
  isComplete: boolean;
}

/** Constructs the current fetch state from fetch tool packets. */
export const constructCurrentFetchState = (
  packets: FetchToolPacket[]
): FetchState => {
  const startPacket = packets.find(
    (packet) => packet.obj.type === PacketType.FETCH_TOOL_START
  );
  const urlsPacket = packets.find(
    (packet) => packet.obj.type === PacketType.FETCH_TOOL_URLS
  )?.obj as FetchToolUrls | undefined;
  const documentsPacket = packets.find(
    (packet) => packet.obj.type === PacketType.FETCH_TOOL_DOCUMENTS
  )?.obj as FetchToolDocuments | undefined;
  const sectionEnd = packets.find(
    (packet) =>
      packet.obj.type === PacketType.SECTION_END ||
      packet.obj.type === PacketType.ERROR
  );

  const urls = urlsPacket?.urls || [];
  const documents = documentsPacket?.documents || [];
  const hasStarted = Boolean(startPacket);
  const isLoading = hasStarted && !documentsPacket;
  const isComplete = Boolean(startPacket && sectionEnd);

  return { urls, documents, hasStarted, isLoading, isComplete };
};
