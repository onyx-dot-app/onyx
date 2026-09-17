import { type SearchDoc } from "@/chat/contracts/documents";
import { UserFileStatus, type ProjectFile } from "@/chat/contracts/projects";
import { ChatFileType } from "@/chat/interfaces";
import {
  type PacketObj,
  type ChatItem,
  type ResponseItem,
  type PacketIdentity,
  type Packet,
  type Placement,
} from "@/chat/streamingModels";

// Shared ProjectFile builder so the file's shape lives in one place across tests.
export function makeProjectFile(
  overrides: Partial<ProjectFile> = {},
): ProjectFile {
  return {
    id: "f1",
    name: "file.pdf",
    file_id: "f1",
    status: UserFileStatus.COMPLETED,
    chat_file_type: ChatFileType.DOCUMENT,
    token_count: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export function makeItem(
  content: ChatItem,
  placement: Partial<Placement> = {},
  id = "message",
): ResponseItem {
  const identity: PacketIdentity = {
    response_id: 1,
    run_id: "root",
    message_id: id,
    part_id: content.kind,
  };
  if (content.kind === "tool") identity.tool_call_id = id;
  return { identity, placement: { turn_index: 0, ...placement }, content };
}
export function makePacket(obj: PacketObj, id = "message"): Packet {
  return {
    identity: {
      response_id: 1,
      run_id: "root",
      message_id: id,
      part_id: "text",
    },
    obj,
  };
}
export function packetForItem(item: ResponseItem): Packet {
  return {
    identity: item.identity,
    obj: { type: "item_update", item: item.content },
  };
}
export function makeCitationPacket(
  citationNumber: number,
  documentId: string,
): Packet {
  return packetForItem(
    makeItem(
      {
        kind: "text",
        text: "",
        purpose: "answer",
        status: "running",
        documents: [],
        citations: [
          { citation_number: citationNumber, document_id: documentId },
        ],
      },
      {},
      `citation-${documentId}`,
    ),
  );
}

export function makeSearchDoc(overrides: Partial<SearchDoc> = {}): SearchDoc {
  return {
    document_id: "d1",
    semantic_identifier: "Doc One",
    link: "https://example.com/doc-one",
    blurb: "A blurb.",
    source_type: "web",
    score: 0.9,
    updated_at: "2026-01-01T00:00:00Z",
    match_highlights: [],
    metadata: {},
    is_internet: true,
    chunk_ind: 0,
    boost: 0,
    hidden: false,
    primary_owners: null,
    secondary_owners: null,
    is_relevant: null,
    relevance_explanation: null,
    file_id: null,
    ...overrides,
  };
}

export function makeSearchDocsPacket(
  docs: SearchDoc[],
  kind: "search" | "open_url" = "search",
): Packet {
  return packetForItem(
    makeItem(
      {
        kind: "tool",
        name: kind === "search" ? "internal_search" : "open_url",
        arguments: {},
        status: "complete",
        output: "",
        metadata: {
          type: "search_result",
          queries: [],
          sources: [],
          search_docs: docs,
          displayed_docs: null,
          citation_mapping: {},
          time_filter_start: null,
          time_filter_end: null,
        },
      },
      {},
      kind,
    ),
  );
}
export function makeMessageStartPacket(
  finalDocuments: SearchDoc[] = [],
): Packet {
  return packetForItem(
    makeItem({
      kind: "text",
      text: "",
      purpose: "answer",
      status: "running",
      documents: finalDocuments,
      citations: [],
    }),
  );
}
export function makeStopPacket(): Packet {
  return makePacket({ type: "stop" });
}
