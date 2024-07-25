import {
  DanswerDocument,
  Filters,
  SearchDanswerDocument,
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
  id: number;
  name: string;
  persona_id: number;
  time_created: string;
  shared_status: ChatSessionSharedStatus;
  folder_id: number | null;
  current_alternate_model: string;
}

export interface SearchSession {
  search_session_id: number;
  documents: SearchDanswerDocument[];
  messages: BackendMessage[];
  description: string;
}

export interface Message {
  messageId: number;
  message: string;
  type: "user" | "assistant" | "system" | "error";
  retrievalType?: RetrievalType;
  query?: string | null;
  documents?: DanswerDocument[] | null;
  citations?: CitationMap;
  files: FileDescriptor[];
  toolCalls: ToolCallMetadata[];
  // for rebuilding the message tree
  parentMessageId: number | null;
  childrenMessageIds?: number[];
  latestChildMessageId?: number | null;
  alternateAssistantID?: number | null;
}

export interface BackendChatSession {
  chat_session_id: number;
  description: string;
  persona_id: number;
  persona_name: string;
  messages: BackendMessage[];
  time_created: string;
  shared_status: ChatSessionSharedStatus;
  current_alternate_model?: string;
}

export interface BackendMessage {
  message_id: number;
  comments: any;
  chat_session_id: number;
  parent_message: number | null;
  latest_child_message: number | null;
  message: string;
  rephrased_query: string | null;
  context_docs: { top_documents: DanswerDocument[] } | null;
  message_type: "user" | "assistant" | "system";
  time_sent: string;
  citations: CitationMap;
  files: FileDescriptor[];
  tool_calls: ToolCallFinalResult[];
  alternate_assistant_id?: number | null;
}

export interface DocumentsResponse {
  top_documents: DanswerDocument[];
  rephrased_query: string | null;
}

export interface ImageGenerationDisplay {
  file_ids: string[];
}

export interface StreamingError {
  error: string;
}
