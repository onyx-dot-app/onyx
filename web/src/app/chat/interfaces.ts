import {
  OnyxDocument,
  Filters,
  SearchOnyxDocument,
  StreamStopReason,
} from "@/lib/search/interfaces";

export enum RetrievalType {
  None = "none",
  Search = "search",
  SelectedDocs = "selectedDocs",
}

export enum ChatSessionSharedStatus {
  Private = "private",
  Public = "public",
}

// The number of messages to buffer on the client side.
export const BUFFER_COUNT = 35;

export interface RetrievalDetails {
  run_search: "always" | "never" | "auto";
  real_time: boolean;
  filters?: Filters;
  enable_auto_detect_filters?: boolean | null;
}

type CitationMap = { [key: string]: number };

export enum ChatFileType {
  IMAGE = "image",
  DOCUMENT = "document",
  PLAIN_TEXT = "plain_text",
  CSV = "csv",
}

export interface FileDescriptor {
  id: string;
  type: ChatFileType;
  name?: string | null;

  // FE only
  isUploading?: boolean;
}

export interface LLMRelevanceFilterPacket {
  relevant_chunk_indices: number[];
}

export interface ToolCallMetadata {
  tool_name: string;
  tool_args: Record<string, any>;
  tool_result?: Record<string, any>;
}

export interface ToolCallFinalResult {
  tool_name: string;
  tool_args: Record<string, any>;
  tool_result: Record<string, any>;
}

export interface ChatSession {
  id: string;
  name: string;
  persona_id: number;
  time_created: string;
  shared_status: ChatSessionSharedStatus;
  folder_id: number | null;
  current_alternate_model: string;
}

export interface SearchSession {
  search_session_id: string;
  documents: SearchOnyxDocument[];
  messages: BackendMessage[];
  description: string;
}

export interface Message {
  messageId: number;
  message: string;
  type: "user" | "assistant" | "system" | "error";
  retrievalType?: RetrievalType;
  query?: string | null;
  documents?: OnyxDocument[] | null;
  citations?: CitationMap;
  files: FileDescriptor[];
  toolCall: ToolCallMetadata | null;
  // for rebuilding the message tree
  parentMessageId: number | null;
  childrenMessageIds?: number[];
  latestChildMessageId?: number | null;
  alternateAssistantID?: number | null;
  stackTrace?: string | null;
  overridden_model?: string;
  stopReason?: StreamStopReason | null;
}

export interface BackendChatSession {
  chat_session_id: string;
  description: string;
  persona_id: number;
  persona_name: string;
  persona_icon_color: string | null;
  persona_icon_shape: number | null;
  messages: BackendMessage[];
  time_created: string;
  shared_status: ChatSessionSharedStatus;
  current_alternate_model?: string;
}

export interface BackendMessage {
  message_id: number;
  comments: any;
  chat_session_id: string;
  parent_message: number | null;
  latest_child_message: number | null;
  message: string;
  rephrased_query: string | null;
  context_docs: { top_documents: OnyxDocument[] } | null;
  message_type: "user" | "assistant" | "system";
  time_sent: string;
  citations: CitationMap;
  files: FileDescriptor[];
  tool_call: ToolCallFinalResult | null;
  alternate_assistant_id?: number | null;
  overridden_model?: string;
}

export interface MessageResponseIDInfo {
  user_message_id: number | null;
  reserved_assistant_message_id: number;
}

export interface DocumentsResponse {
  top_documents: OnyxDocument[];
  rephrased_query: string | null;
}

export interface FileChatDisplay {
  file_ids: string[];
}

export interface StreamingError {
  error: string;
  stack_trace: string;
}
