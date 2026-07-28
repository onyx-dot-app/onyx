import { type SearchDoc } from "@/chat/contracts/documents";
import { UserFileStatus, type ProjectFile } from "@/chat/contracts/projects";
import { ChatFileType } from "@/chat/interfaces";
import { type ObjTypes, type Packet } from "@/chat/streamingModels";

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

export function makePacket(obj: ObjTypes, turnIndex = 0): Packet {
  return { placement: { turn_index: turnIndex }, obj };
}

export function makeCitationPacket(
  citationNumber: number,
  documentId: string,
): Packet {
  return makePacket({
    type: "citation_info",
    citation_number: citationNumber,
    document_id: documentId,
  });
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
  return makePacket(
    kind === "open_url"
      ? { type: "open_url_documents", documents: docs }
      : { type: "search_tool_documents_delta", documents: docs },
  );
}

export function makeMessageStartPacket(finalDocuments?: SearchDoc[]): Packet {
  return makePacket({
    type: "message_start",
    id: "m",
    content: "",
    final_documents: finalDocuments ?? null,
  });
}

export function makeStopPacket(): Packet {
  return makePacket({ type: "stop" });
}
