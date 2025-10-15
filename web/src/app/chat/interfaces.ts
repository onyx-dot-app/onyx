import {
  OnyxDocument,
  Filters,
  SearchOnyxDocument,
  StreamStopReason,
} from "@/lib/search/interfaces";
import { Packet } from "./services/streamingModels";

export type FeedbackType = "like" | "dislike";
export type ChatState =
  | "input"
  | "loading"
  | "streaming"
  | "toolBuilding"
  | "uploading";
export interface RegenerationState {
  regenerating: boolean;
  finalMessageIndex: number;
}

export enum RetrievalType {
  None = "none",
  Search = "search",
  SelectedDocs = "selectedDocs",
}

export enum ResearchType {
  LegacyAgentic = "LEGACY_AGENTIC",
  Thoughtful = "THOUGHTFUL",
  Deep = "DEEP",
  Fast = "FAST",
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

// Document ID -> Citation number
export type CitationMap = { [key: string]: number };

export enum ChatFileType {
  IMAGE = "image",
  DOCUMENT = "document",
  PLAIN_TEXT = "plain_text",
  CSV = "csv",
  USER_KNOWLEDGE = "user_knowledge",
}

export const isTextFile = (fileType: ChatFileType) =>
  [
    ChatFileType.PLAIN_TEXT,
    ChatFileType.CSV,
    ChatFileType.USER_KNOWLEDGE,
    ChatFileType.DOCUMENT,
  ].includes(fileType);

export interface FileDescriptor {
  id: string;
  type: ChatFileType;
  name?: string | null;

  user_file_id?: string | null;
  // FE only
  isUploading?: boolean;
}

export interface FileDescriptorWithHighlights extends FileDescriptor {
  match_highlights: string[];
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
  time_updated: string;
  shared_status: ChatSessionSharedStatus;
  project_id: number | null;
  current_alternate_model: string;
  current_temperature_override: number | null;
}

export interface SearchSession {
  search_session_id: string;
  documents: SearchOnyxDocument[];
  messages: BackendMessage[];
  description: string;
}

export interface Message {
  is_generating?: boolean;
  messageId?: number;
  nodeId: number; // Unique identifier for tree structure (can be negative for temp messages)
  message: string;
  type: "user" | "assistant" | "system" | "error";
  retrievalType?: RetrievalType;
  researchType?: ResearchType;
  query?: string | null;
  files: FileDescriptor[];
  toolCall: ToolCallMetadata | null;
  // for rebuilding the message tree - these now use nodeId
  parentNodeId: number | null;
  childrenNodeIds?: number[];
  latestChildNodeId?: number | null;
  alternateAssistantID?: number | null;
  stackTrace?: string | null;
  overridden_model?: string;
  stopReason?: StreamStopReason | null;

  // new gen
  packets: Packet[];

  // cached values for easy access
  documents?: OnyxDocument[] | null;
  citations?: CitationMap;
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
  time_updated: string;
  shared_status: ChatSessionSharedStatus;
  current_temperature_override: number | null;
  current_alternate_model?: string;

  packets: Packet[][];
}

export interface BackendMessage {
  message_id: number;
  message_type: string;
  research_type: string | null;
  parent_message: number | null;
  latest_child_message: number | null;
  message: string;
  rephrased_query: string | null;
  context_docs: { top_documents: OnyxDocument[] } | null;
  time_sent: string;
  overridden_model: string;
  alternate_assistant_id: number | null;
  chat_session_id: string;
  citations: CitationMap | null;
  files: FileDescriptor[];
  tool_call: ToolCallFinalResult | null;

  sub_questions: SubQuestionDetail[];
  // Keeping existing properties
  comments: any;
  parentMessageId: number | null;
  refined_answer_improvement: boolean | null;
  is_agentic: boolean | null;
}

export interface MessageResponseIDInfo {
  user_message_id: number | null;
  reserved_assistant_message_id: number;
}

export interface UserKnowledgeFilePacket {
  user_files: FileDescriptor[];
}

export interface DocumentsResponse {
  top_documents: OnyxDocument[];
  rephrased_query: string | null;
  level?: number | null;
  level_question_num?: number | null;
}

export interface FileChatDisplay {
  file_ids: string[];
}

export interface StreamingError {
  error: string;
  stack_trace: string;
}

export interface InputPrompt {
  id: number;
  prompt: string;
  content: string;
  active: boolean;
  is_public: boolean;
}

export interface EditPromptModalProps {
  onClose: () => void;

  promptId: number;
  editInputPrompt: (
    promptId: number,
    values: CreateInputPromptRequest
  ) => Promise<void>;
}
export interface CreateInputPromptRequest {
  prompt: string;
  content: string;
}

export interface AddPromptModalProps {
  onClose: () => void;
  onSubmit: (promptData: CreateInputPromptRequest) => void;
}
export interface PromptData {
  id: number;
  prompt: string;
  content: string;
}

/**
 * // Start of Selection
 */

export interface BaseQuestionIdentifier {
  level: number;
  level_question_num: number;
}

export interface SubQuestionDetail extends BaseQuestionIdentifier {
  question: string;
  answer: string;
  sub_queries?: SubQueryDetail[] | null;
  context_docs?: { top_documents: OnyxDocument[] } | null;
  is_complete?: boolean;
  is_stopped?: boolean;
  answer_streaming?: boolean;
}

export interface SubQueryDetail {
  query: string;
  query_id: number;
  doc_ids?: number[] | null;
}
