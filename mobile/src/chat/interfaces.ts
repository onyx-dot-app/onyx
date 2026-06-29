// Minimal core chat types. Rich fields (documents/citations/multi-model) are
// added in their own phases.

import { Packet } from "./streamingModels";

export type MessageType = "user" | "assistant" | "system" | "error";

// web also has "toolBuilding"; omitted until tools land.
export type ChatState = "input" | "loading" | "streaming" | "uploading";

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
  messageId?: number;
  nodeId: number;
  parentNodeId: number | null;
  childrenNodeIds?: number[];
  latestChildNodeId?: number | null;
  type: MessageType;
  message: string;
  files: FileDescriptor[];
  packets: Packet[];
}

// One row of a loaded session snapshot (GET get-chat-session); minimal subset.
export interface BackendMessage {
  message_id: number;
  message_type: string;
  parent_message: number | null;
  latest_child_message: number | null;
  message: string;
  files: FileDescriptor[];
  time_sent: string;
  error: string | null;
}

// Session snapshot for hydration; `packets` is indexed by assistant-message ordinal.
export interface BackendChatSession {
  chat_session_id: string;
  description: string;
  persona_id: number;
  messages: BackendMessage[];
  packets: Packet[][];
  time_created: string;
  time_updated?: string;
  current_run?: { run_id: number } | null; // set while a run is in flight
}
