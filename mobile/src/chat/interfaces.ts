import { Packet } from "./streamingModels";

// agent_results is the hidden question node of an automatic follow-up response.
export type MessageType =
  "user" | "assistant" | "agent_results" | "system" | "error";

export type ChatState =
  "input" | "loading" | "streaming" | "uploading" | "settling" | "unconfirmed";

export enum ChatFileType {
  IMAGE = "image",
  DOCUMENT = "document",
  PLAIN_TEXT = "plain_text",
  TABULAR = "tabular",
  USER_KNOWLEDGE = "user_knowledge",
}

export interface FileDescriptor {
  id: string;
  type: ChatFileType;
  name?: string | null;
  user_file_id?: string | null;
  isUploading?: boolean; // FE only
}

// nodeId = client tree key (negative/temp until the backend assigns messageId).
export interface Message {
  // Null means no saved SDK outcome; absent means an older API.
  responseStatus?:
    | "running"
    | "suspended"
    | "complete"
    | "limit"
    | "cancelled"
    | "error"
    | null;
  messageId?: number;
  nodeId: number;
  parentNodeId: number | null;
  childrenNodeIds?: number[];
  latestChildNodeId?: number | null;
  type: MessageType;
  message: string;
  files: FileDescriptor[];
  packets: Packet[];
  // Backend StreamingError.error_code on an errored turn; titles the error box.
  errorCode?: string | null;
  // Epoch ms the stream started, for the timeline's elapsed timer. Only set while streaming; a
  // hydrated turn has none and falls back to `processingDurationSeconds`.
  streamingStartedAt?: number;
  // Backend `processing_duration_seconds`; becomes the header's "Thought for Xs".
  processingDurationSeconds?: number | null;
}

// Subset of a loaded session-snapshot row (GET get-chat-session).
export interface BackendMessage {
  response_status?: Message["responseStatus"];
  message_id: number;
  message_type: string;
  parent_message: number | null;
  latest_child_message: number | null;
  message: string;
  files: FileDescriptor[];
  time_sent: string;
  error: string | null;
  processing_duration_seconds?: number | null;
}

// A running response's stream. `stream_id` is not a message id; `response_ids` names the response
// rows it writes, in model order for a multi-model turn.
export interface ChatStream {
  stream_id: number;
  response_ids: number[];
}

// `packets` is indexed by assistant-message ordinal.
export interface BackendChatSession {
  chat_session_id: string;
  description: string;
  persona_id: number;
  messages: BackendMessage[];
  packets: Packet[][];
  time_created: string;
  time_updated?: string;
  current_stream?: ChatStream | null; // set while a run is in flight
  // The status route's `approvals_version` for the requests this load shows.
  approvals_version?: string;
}
