// Core streaming-packet contracts (NDJSON wire shapes). Mobile-native mirror of web's
// `web/src/app/app/services/streamingModels.ts` — the full `PacketType` enum + every packet obj
// interface, so the ported grouping engine + timeline helpers compile once and each future tool
// renderer phase adds only its renderer (no enum/interface churn). Document arrays carry mobile's
// `SearchDoc` (not web's `OnyxDocument`); the root, non-`Packet`-wrapped stream members
// (`MessageResponseIDInfo`, `StreamingError`) are mobile-specific and kept.

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
  TOP_LEVEL_BRANCHING = "top_level_branching",
  ERROR = "error",

  // Specific tool packets
  SEARCH_TOOL_START = "search_tool_start",
  SEARCH_TOOL_QUERIES_DELTA = "search_tool_queries_delta",
  SEARCH_TOOL_FILTER_DELTA = "search_tool_filter_delta",
  SEARCH_TOOL_DOCUMENTS_DELTA = "search_tool_documents_delta",
  IMAGE_GENERATION_TOOL_START = "image_generation_start",
  IMAGE_GENERATION_TOOL_DELTA = "image_generation_final",
  PYTHON_TOOL_START = "python_tool_start",
  PYTHON_TOOL_DELTA = "python_tool_delta",
  // Open-URL / fetch tool (web names these FETCH_TOOL_*; the wire values are open_url_*).
  FETCH_TOOL_START = "open_url_start",
  FETCH_TOOL_URLS = "open_url_urls",
  FETCH_TOOL_DOCUMENTS = "open_url_documents",

  // Streams tool args before the tool executes.
  TOOL_CALL_ARGUMENT_DELTA = "tool_call_argument_delta",

  // Custom tool packets
  CUSTOM_TOOL_START = "custom_tool_start",
  CUSTOM_TOOL_ARGS = "custom_tool_args",
  CUSTOM_TOOL_DELTA = "custom_tool_delta",

  // File reader tool packets
  FILE_READER_START = "file_reader_start",
  FILE_READER_RESULT = "file_reader_result",

  // Memory tool packets
  MEMORY_TOOL_START = "memory_tool_start",
  MEMORY_TOOL_DELTA = "memory_tool_delta",
  MEMORY_TOOL_NO_ACCESS = "memory_tool_no_access",

  // Reasoning packets
  REASONING_START = "reasoning_start",
  REASONING_DELTA = "reasoning_delta",
  REASONING_DONE = "reasoning_done",

  // Citation packets. Only `citation_info` is emitted by the backend (citation_start/end are
  // declared for parity but never sent).
  CITATION_START = "citation_start",
  CITATION_END = "citation_end",
  CITATION_INFO = "citation_info",

  // Deep Research packets
  DEEP_RESEARCH_PLAN_START = "deep_research_plan_start",
  DEEP_RESEARCH_PLAN_DELTA = "deep_research_plan_delta",
  RESEARCH_AGENT_START = "research_agent_start",
  INTERMEDIATE_REPORT_START = "intermediate_report_start",
  INTERMEDIATE_REPORT_DELTA = "intermediate_report_delta",
  INTERMEDIATE_REPORT_CITED_DOCS = "intermediate_report_cited_docs",

  // Coding Agent packets
  CODING_AGENT_START = "coding_agent_start",
  CODING_AGENT_THINKING_DELTA = "coding_agent_thinking_delta",
  CODING_AGENT_FINAL = "coding_agent_final",

  // Bash Tool packets
  BASH_TOOL_START = "bash_tool_start",
  BASH_TOOL_DELTA = "bash_tool_delta",
}

export const CODE_INTERPRETER_TOOL_TYPES = {
  PYTHON: "python",
} as const;

// Basic message packets
export interface MessageStart extends BaseObj {
  id: string;
  type: "message_start";
  content: string;
  pre_answer_processing_seconds?: number;
  // Authoritative cited-doc set for the turn (present once the answer starts).
  final_documents?: SearchDoc[] | null;
}

export interface MessageDelta extends BaseObj {
  type: "message_delta";
  content: string;
}

export interface MessageEnd extends BaseObj {
  type: "message_end";
}

// Control packets
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

export interface TopLevelBranching extends BaseObj {
  type: "top_level_branching";
  num_parallel_branches: number;
}

export interface PacketError extends BaseObj {
  type: "error";
  message?: string;
}

// Filtered by the consumer, not the parser. Connection keepalive during silent stretches.
export interface ChatHeartbeat extends BaseObj {
  type: "chat_heartbeat";
}

// Search tool
export interface SearchToolStart extends BaseObj {
  type: "search_tool_start";
  is_internet_search?: boolean;
}

export interface SearchToolQueriesDelta extends BaseObj {
  type: "search_tool_queries_delta";
  queries: string[];
}

export interface SearchToolFilterDelta extends BaseObj {
  type: "search_tool_filter_delta";
  // Connector/source values this search is scoped to (empty == all).
  sources: string[];
}

export interface SearchToolDocumentsDelta extends BaseObj {
  type: "search_tool_documents_delta";
  documents: SearchDoc[];
}

// Image generation
export type ImageShape = "square" | "landscape" | "portrait";

export interface GeneratedImage {
  file_id: string;
  url: string;
  revised_prompt: string;
  shape?: ImageShape;
}

export interface ImageGenerationToolStart extends BaseObj {
  type: "image_generation_start";
}

export interface ImageGenerationToolDelta extends BaseObj {
  type: "image_generation_final";
  images: GeneratedImage[];
}

// Python / code interpreter
export interface PythonToolStart extends BaseObj {
  type: "python_tool_start";
  code: string;
}

export interface PythonToolDelta extends BaseObj {
  type: "python_tool_delta";
  stdout: string;
  stderr: string;
  file_ids: string[];
}

export interface ToolCallArgumentDelta extends BaseObj {
  type: "tool_call_argument_delta";
  tool_type: string;
  tool_id: string;
  argument_deltas: Record<string, unknown>;
}

// Open-URL / fetch tool
export interface FetchToolStart extends BaseObj {
  type: "open_url_start";
}

export interface FetchToolUrls extends BaseObj {
  type: "open_url_urls";
  urls: string[];
}

export interface FetchToolDocuments extends BaseObj {
  type: "open_url_documents";
  documents: SearchDoc[];
}

// Custom tool
export interface CustomToolErrorInfo {
  is_auth_error: boolean;
  status_code: number;
  message: string;
}

export interface CustomToolStart extends BaseObj {
  type: "custom_tool_start";
  tool_name: string;
  tool_id?: number | null;
}

export interface CustomToolArgs extends BaseObj {
  type: "custom_tool_args";
  tool_name: string;
  tool_args: Record<string, unknown>;
}

export interface CustomToolDelta extends BaseObj {
  type: "custom_tool_delta";
  tool_name: string;
  tool_id?: number | null;
  response_type: string;
  data?: unknown;
  file_ids?: string[] | null;
  error?: CustomToolErrorInfo | null;
}

// File reader
export interface FileReaderStart extends BaseObj {
  type: "file_reader_start";
}

export interface FileReaderResult extends BaseObj {
  type: "file_reader_result";
  file_name: string;
  file_id: string;
  start_char: number;
  end_char: number;
  total_chars: number;
  preview_start: string;
  preview_end: string;
}

// Memory tool
export interface MemoryToolStart extends BaseObj {
  type: "memory_tool_start";
}

export interface MemoryToolDelta extends BaseObj {
  type: "memory_tool_delta";
  memory_text: string;
  operation: "add" | "update";
  memory_id: number | null;
  index: number | null;
}

export interface MemoryToolNoAccess extends BaseObj {
  type: "memory_tool_no_access";
}

// Reasoning
export interface ReasoningStart extends BaseObj {
  type: "reasoning_start";
}

export interface ReasoningDelta extends BaseObj {
  type: "reasoning_delta";
  reasoning: string;
}

export interface ReasoningDone extends BaseObj {
  type: "reasoning_done";
}

// Citations
// The deduped, first-cite-ordered citation read-model (distinct from the wire `CitationInfo`).
export interface StreamingCitation {
  citation_num: number;
  document_id: string;
}

export interface CitationStart extends BaseObj {
  type: "citation_start";
}

export interface CitationInfo extends BaseObj {
  type: "citation_info";
  citation_number: number;
  document_id: string;
}

// Deep research
export interface DeepResearchPlanStart extends BaseObj {
  type: "deep_research_plan_start";
}

export interface DeepResearchPlanDelta extends BaseObj {
  type: "deep_research_plan_delta";
  content: string;
}

export interface ResearchAgentStart extends BaseObj {
  type: "research_agent_start";
  research_task: string;
}

export interface IntermediateReportStart extends BaseObj {
  type: "intermediate_report_start";
}

export interface IntermediateReportDelta extends BaseObj {
  type: "intermediate_report_delta";
  content: string;
}

export interface IntermediateReportCitedDocs extends BaseObj {
  type: "intermediate_report_cited_docs";
  cited_docs: SearchDoc[] | null;
}

// Coding agent + bash
export interface CodingAgentStart extends BaseObj {
  type: "coding_agent_start";
  query: string;
  repo: string | null;
}

export interface CodingAgentThinkingDelta extends BaseObj {
  type: "coding_agent_thinking_delta";
  content: string;
}

export interface CodingAgentFinal extends BaseObj {
  type: "coding_agent_final";
  answer: string;
}

export interface BashToolStart extends BaseObj {
  type: "bash_tool_start";
  cmd: string;
}

export interface BashToolDelta extends BaseObj {
  type: "bash_tool_delta";
  stdout: string;
  stderr: string;
  exit_code: number | null;
  timed_out: boolean;
}

// Unions
export type ChatObj = MessageStart | MessageDelta | MessageEnd;

export type SearchToolObj =
  | SearchToolStart
  | SearchToolQueriesDelta
  | SearchToolFilterDelta
  | SearchToolDocumentsDelta
  | SectionEnd
  | PacketError;

export type ImageGenerationToolObj =
  | ImageGenerationToolStart
  | ImageGenerationToolDelta
  | SectionEnd
  | PacketError;

export type PythonToolObj =
  | PythonToolStart
  | PythonToolDelta
  | ToolCallArgumentDelta
  | SectionEnd
  | PacketError;

export type FetchToolObj =
  | FetchToolStart
  | FetchToolUrls
  | FetchToolDocuments
  | SectionEnd
  | PacketError;

export type CustomToolObj =
  | CustomToolStart
  | CustomToolArgs
  | CustomToolDelta
  | SectionEnd
  | PacketError;

export type FileReaderToolObj =
  | FileReaderStart
  | FileReaderResult
  | SectionEnd
  | PacketError;

export type MemoryToolObj =
  | MemoryToolStart
  | MemoryToolDelta
  | MemoryToolNoAccess
  | SectionEnd
  | PacketError;

export type NewToolObj =
  | SearchToolObj
  | ImageGenerationToolObj
  | PythonToolObj
  | FetchToolObj
  | CustomToolObj
  | FileReaderToolObj
  | MemoryToolObj;

export type ReasoningObj =
  | ReasoningStart
  | ReasoningDelta
  | ReasoningDone
  | SectionEnd
  | PacketError;

export type CitationObj =
  | CitationStart
  | CitationInfo
  | SectionEnd
  | PacketError;

export type DeepResearchPlanObj =
  | DeepResearchPlanStart
  | DeepResearchPlanDelta
  | SectionEnd;

export type ResearchAgentObj =
  | ResearchAgentStart
  | IntermediateReportStart
  | IntermediateReportDelta
  | IntermediateReportCitedDocs
  | SectionEnd;

export type CodingAgentObj =
  | CodingAgentStart
  | CodingAgentThinkingDelta
  | CodingAgentFinal
  | BashToolStart
  | BashToolDelta
  | SectionEnd
  | PacketError;

// Union type for all possible streaming objects.
export type ObjTypes =
  | ChatObj
  | NewToolObj
  | ReasoningObj
  | Stop
  | ChatHeartbeat
  | SectionEnd
  | TopLevelBranching
  | CitationObj
  | DeepResearchPlanObj
  | ResearchAgentObj
  | CodingAgentObj
  | PacketError;

export interface Placement {
  turn_index: number;
  // Parallel tool calls: same turn_index, different tab_index run in parallel.
  tab_index?: number;
  sub_turn_index?: number | null;
  // Multi-model answer generation: which model produced this packet.
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
