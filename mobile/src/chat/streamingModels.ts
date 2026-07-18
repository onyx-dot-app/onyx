// Core streaming-packet contracts (NDJSON wire shapes).

import type { SearchDoc } from "@/chat/contracts/documents";

interface BaseObj {
  type: string;
}

export enum PacketType {
  MESSAGE_START = "message_start",
  MESSAGE_DELTA = "message_delta",
  MESSAGE_END = "message_end",
  STOP = "stop",
  SECTION_END = "section_end",
  ERROR = "error",
  // Rich-chat (9a): citations + the documents that back them. `citation_info` is the ONLY citation
  // packet the backend emits (web's citation_start/end are declared but never sent).
  CITATION_INFO = "citation_info",
  SEARCH_TOOL_DOCUMENTS_DELTA = "search_tool_documents_delta",
  OPEN_URL_DOCUMENTS = "open_url_documents",
}

export interface MessageStart extends BaseObj {
  id: string;
  type: "message_start";
  content: string;
  pre_answer_processing_seconds?: number;
  // Authoritative cited-doc set for the turn (present once the answer starts).
  final_documents?: SearchDoc[] | null;
}

export interface CitationInfo extends BaseObj {
  type: "citation_info";
  citation_number: number;
  document_id: string;
}

export interface SearchToolDocumentsDelta extends BaseObj {
  type: "search_tool_documents_delta";
  documents: SearchDoc[];
}

export interface OpenUrlDocuments extends BaseObj {
  type: "open_url_documents";
  documents: SearchDoc[];
}

export interface MessageDelta extends BaseObj {
  type: "message_delta";
  content: string;
}

export interface MessageEnd extends BaseObj {
  type: "message_end";
}

export enum StopReason {
  FINISHED = "finished",
  USER_CANCELLED = "user_cancelled",
}

export interface Stop extends BaseObj {
  type: "stop";
  stop_reason?: StopReason;
}

export interface SectionEnd extends BaseObj {
  type: "section_end";
}

export interface PacketError extends BaseObj {
  type: "error";
  message?: string;
}

// Filtered by the consumer, not the parser. No enum member (matches backend).
export interface ChatHeartbeat extends BaseObj {
  type: "chat_heartbeat";
}

export type ChatObj = MessageStart | MessageDelta | MessageEnd;

export type ObjTypes =
  | ChatObj
  | Stop
  | SectionEnd
  | PacketError
  | ChatHeartbeat
  | CitationInfo
  | SearchToolDocumentsDelta
  | OpenUrlDocuments;

export interface Placement {
  turn_index: number;
  tab_index?: number;
  sub_turn_index?: number | null;
  model_index?: number | null;
}

export interface Packet {
  placement: Placement;
  obj: ObjTypes;
}

// Root object (not wrapped in Packet.obj); wire omits `type`, so discriminate by
// field presence (`"user_message_id" in obj`), never `obj.type`.
export interface MessageResponseIDInfo {
  type?: "message_id_info";
  user_message_id: number | null;
  reserved_assistant_message_id: number;
}

// Root-level error (backend `StreamingError`), not wrapped in Packet.obj — discriminate
// by top-level `error`, not `obj.type`. Dropping it silently leaves the turn stuck on "…".
export interface StreamingError {
  error: string;
  stack_trace?: string | null;
  error_code?: string | null;
  is_retryable?: boolean;
  details?: Record<string, unknown> | null;
}
