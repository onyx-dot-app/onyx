import {
  PacketType,
  FetchToolPacket,
  FetchToolUrls,
  FetchToolDocuments,
  OnyxDocument,
} from "@/lib/types";

export const INITIAL_URLS_TO_SHOW = 3;
export const URLS_PER_EXPANSION = 5;

export interface FetchState {
  urls: string[];
  documents: OnyxDocument[];
  hasStarted: boolean;
  isLoading: boolean;
  isComplete: boolean;
}

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
