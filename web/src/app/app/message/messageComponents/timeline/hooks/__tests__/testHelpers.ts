/**
 * Shared test helpers for packet processing tests
 */
import {
  Packet,
  PacketType,
  Placement,
  StopReason,
} from "@/app/app/services/streamingModels";
import { OnyxDocument } from "@/lib/search/interfaces";

// Core packet factory
export function createPacket(
  type: PacketType,
  placement: Partial<Placement> = {},
  objOverrides: Record<string, unknown> = {}
): Packet {
  return {
    placement: {
      turn_index: 0,
      tab_index: 0,
      ...placement,
    },
    obj: {
      type,
      ...objOverrides,
    },
  } as Packet;
}

// Stop packet
export function createStopPacket(
  stopReason?: StopReason,
  placement: Partial<Placement> = {}
): Packet {
  return createPacket(PacketType.STOP, placement, {
    stop_reason: stopReason,
  });
}

// Branching packet
export function createBranchingPacket(
  numBranches: number,
  turnIndex: number
): Packet {
  return createPacket(
    PacketType.TOP_LEVEL_BRANCHING,
    { turn_index: turnIndex },
    { num_parallel_branches: numBranches }
  );
}

// Message packet
export function createMessageStartPacket(
  placement: Partial<Placement> = {},
  preAnswerProcessingSeconds?: number
): Packet {
  return createPacket(PacketType.MESSAGE_START, placement, {
    id: "msg-1",
    content: "",
    final_documents: null,
    ...(preAnswerProcessingSeconds !== undefined && {
      pre_answer_processing_seconds: preAnswerProcessingSeconds,
    }),
  });
}

// Citation packet
export function createCitationPacket(
  citationNumber: number,
  documentId: string,
  placement: Partial<Placement> = {}
): Packet {
  return createPacket(PacketType.CITATION_INFO, placement, {
    citation_number: citationNumber,
    document_id: documentId,
  });
}

// Image generation packet
export function createImageDeltaPacket(
  imageCount: number,
  placement: Partial<Placement> = {}
): Packet {
  const images = Array.from({ length: imageCount }, (_, i) => ({
    file_id: `file-${i}`,
    url: `https://example.com/image-${i}.png`,
    revised_prompt: `Image ${i}`,
  }));
  return createPacket(PacketType.IMAGE_GENERATION_TOOL_DELTA, placement, {
    images,
  });
}

// Search Tool helpers
export function createSearchToolStartPacket(
  placement: Partial<Placement> = {},
  isInternetSearch?: boolean
): Packet {
  return createPacket(PacketType.SEARCH_TOOL_START, placement, {
    ...(isInternetSearch !== undefined && {
      is_internet_search: isInternetSearch,
    }),
  });
}

export function createSearchToolQueriesPacket(
  queries: string[],
  placement: Partial<Placement> = {}
): Packet {
  return createPacket(PacketType.SEARCH_TOOL_QUERIES_DELTA, placement, {
    queries,
  });
}

export function createSearchToolDocumentsPacket(
  documents: Partial<OnyxDocument>[],
  placement: Partial<Placement> = {}
): Packet {
  return createPacket(PacketType.SEARCH_TOOL_DOCUMENTS_DELTA, placement, {
    documents,
  });
}

// Fetch Tool helpers
export function createFetchToolStartPacket(
  placement: Partial<Placement> = {}
): Packet {
  return createPacket(PacketType.FETCH_TOOL_START, placement);
}

export function createFetchToolUrlsPacket(
  urls: string[],
  placement: Partial<Placement> = {}
): Packet {
  return createPacket(PacketType.FETCH_TOOL_URLS, placement, {
    urls,
  });
}

export function createFetchToolDocumentsPacket(
  documents: Partial<OnyxDocument>[],
  placement: Partial<Placement> = {}
): Packet {
  return createPacket(PacketType.FETCH_TOOL_DOCUMENTS, placement, {
    documents,
  });
}

// Python Tool helpers
export function createPythonToolStartPacket(
  code: string,
  placement: Partial<Placement> = {}
): Packet {
  return createPacket(PacketType.PYTHON_TOOL_START, placement, {
    code,
  });
}

export function createPythonToolDeltaPacket(
  stdout: string,
  stderr: string,
  fileIds: string[],
  placement: Partial<Placement> = {}
): Packet {
  return createPacket(PacketType.PYTHON_TOOL_DELTA, placement, {
    stdout,
    stderr,
    file_ids: fileIds,
  });
}
