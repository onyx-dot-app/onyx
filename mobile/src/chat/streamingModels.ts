// Streaming-packet contracts (NDJSON wire shapes). Mirror of web's streamingModels, with mobile's
// SearchDoc for document arrays and the mobile-only root types at the bottom.

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

  SEARCH_TOOL_START = "search_tool_start",
  SEARCH_TOOL_QUERIES_DELTA = "search_tool_queries_delta",
  SEARCH_TOOL_FILTER_DELTA = "search_tool_filter_delta",
  SEARCH_TOOL_DOCUMENTS_DELTA = "search_tool_documents_delta",
  IMAGE_GENERATION_TOOL_START = "image_generation_start",
  IMAGE_GENERATION_TOOL_DELTA = "image_generation_final",
  PYTHON_TOOL_START = "python_tool_start",
  PYTHON_TOOL_DELTA = "python_tool_delta",
  // web names these FETCH_TOOL_*; the wire values are open_url_*
  FETCH_TOOL_START = "open_url_start",
  FETCH_TOOL_URLS = "open_url_urls",
  FETCH_TOOL_DOCUMENTS = "open_url_documents",

  TOOL_CALL_ARGUMENT_DELTA = "tool_call_argument_delta",

  CUSTOM_TOOL_START = "custom_tool_start",
  CUSTOM_TOOL_ARGS = "custom_tool_args",
  CUSTOM_TOOL_DELTA = "custom_tool_delta",

  FILE_READER_START = "file_reader_start",
  FILE_READER_RESULT = "file_reader_result",

  MEMORY_TOOL_START = "memory_tool_start",
  MEMORY_TOOL_DELTA = "memory_tool_delta",
  MEMORY_TOOL_NO_ACCESS = "memory_tool_no_access",

  REASONING_START = "reasoning_start",
  REASONING_DELTA = "reasoning_delta",
  REASONING_DONE = "reasoning_done",

  // Only citation_info is emitted; citation_start/end are declared for parity but never sent.
  CITATION_START = "citation_start",
  CITATION_END = "citation_end",
  CITATION_INFO = "citation_info",

  DEEP_RESEARCH_PLAN_START = "deep_research_plan_start",
  DEEP_RESEARCH_PLAN_DELTA = "deep_research_plan_delta",
  RESEARCH_AGENT_START = "research_agent_start",
  INTERMEDIATE_REPORT_START = "intermediate_report_start",
  INTERMEDIATE_REPORT_DELTA = "intermediate_report_delta",
  INTERMEDIATE_REPORT_CITED_DOCS = "intermediate_report_cited_docs",

  CODING_AGENT_START = "coding_agent_start",
  CODING_AGENT_THINKING_DELTA = "coding_agent_thinking_delta",
  CODING_AGENT_FINAL = "coding_agent_final",

  BASH_TOOL_START = "bash_tool_start",
  BASH_TOOL_DELTA = "bash_tool_delta",

  CODE_MODE_START = "code_mode_start",
  CODE_MODE_DELTA = "code_mode_delta",

  // A tool call waits for the user's decision; they never name a timeline step.
  TOOL_APPROVAL_REQUEST = "tool_approval_request",
  TOOL_APPROVAL_RESOLVED = "tool_approval_resolved",
}

export const CODE_INTERPRETER_TOOL_TYPES = {
  PYTHON: "python",
} as const;

// tool_type of the argument deltas that stream a code mode program
export const CODE_MODE_TOOL_TYPE = "execute_code";

export interface MessageStart extends BaseObj {
  id: string;
  type: "message_start";
  content: string;
  pre_answer_processing_seconds?: number;
  final_documents?: SearchDoc[] | null;
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
  // The turn reached its execution deadline.
  TIMED_OUT = "timed_out",
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

export interface ChatHeartbeat extends BaseObj {
  type: "chat_heartbeat";
}

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
  sources: string[];
}

export interface SearchToolDocumentsDelta extends BaseObj {
  type: "search_tool_documents_delta";
  documents: SearchDoc[];
}

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

export interface CustomToolErrorInfo {
  is_auth_error: boolean;
  status_code: number | null;
  message: string;
}

export interface CustomToolStart extends BaseObj {
  type: "custom_tool_start";
  // Qualified name that identifies the tool; not for display.
  tool_name: string;
  // Absent from servers that predate it.
  display_name?: string;
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

export type CodeModeStatus =
  "running" | "completed" | "failed" | "timed_out" | "terminated" | "cancelled";

export interface CodeModeStart extends BaseObj {
  type: "code_mode_start";
  code: string;
  cell_id?: number | null;
  observation?: number;
}

export interface CodeModeDelta extends BaseObj {
  type: "code_mode_delta";
  stdout: string;
  replace_stdout?: boolean;
  result?: string | null;
  error?: string | null;
  status?: CodeModeStatus | null;
  duration_seconds?: number | null;
  tool_call_count?: number | null;
  stored_keys?: string[] | null;
  cell_id?: number | null;
  observation?: number | null;
  response_ended?: boolean;
}

export type ChatObj = MessageStart | MessageDelta | MessageEnd;

export type SearchToolObj =
  | SearchToolStart
  | SearchToolQueriesDelta
  | SearchToolFilterDelta
  | SearchToolDocumentsDelta
  | SectionEnd
  | PacketError;

export interface ToolApprovalRequest extends BaseObj {
  type: "tool_approval_request";
  approval_id: string;
  tool_call_id: string;
  tool_name: string;
  display_name: string;
  arguments: Record<string, unknown>;
  // ISO 8601; shown to the user, never used to close the request
  expires_at: string;
}

export interface ToolApprovalResolved extends BaseObj {
  type: "tool_approval_resolved";
  approval_id: string;
  // "approved_for_chat": approved by a grant for the chat's later calls of the tool.
  // "disabled": an approval found the tool disabled, so the call did not run.
  outcome:
    | "approved"
    | "approved_for_chat"
    | "rejected"
    | "expired"
    | "disabled"
    | "cancelled";
}

export type ToolApprovalObj = ToolApprovalRequest | ToolApprovalResolved;

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
  CustomToolStart | CustomToolArgs | CustomToolDelta | SectionEnd | PacketError;

export type FileReaderToolObj =
  FileReaderStart | FileReaderResult | SectionEnd | PacketError;

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
  ReasoningStart | ReasoningDelta | ReasoningDone | SectionEnd | PacketError;

export type CitationObj =
  CitationStart | CitationInfo | SectionEnd | PacketError;

export type DeepResearchPlanObj =
  DeepResearchPlanStart | DeepResearchPlanDelta | SectionEnd;

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
  | CodeModeStart
  | CodeModeDelta
  | ToolApprovalObj
  | PacketError;

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

// Root object (not wrapped in Packet.obj); discriminate by field presence, never obj.type.
export interface MessageResponseIDInfo {
  type?: "message_id_info";
  user_message_id: number | null;
  reserved_assistant_message_id: number;
}

// Root-level error; discriminate by top-level `error`, not obj.type. Dropping it leaves the turn
// stuck on "…".
export interface StreamingError {
  error: string;
  stack_trace?: string | null;
  error_code?: string | null;
  is_retryable?: boolean;
  details?: Record<string, unknown> | null;
}

// A user stop aborts the reader before the backend's own `stop` packet can arrive, so without this
// the turn keeps looking like it is streaming — live timer included — until a reload, where the
// backend replays an OverallStop.
export function buildUserCancelledStopPacket(packets: Packet[]): Packet {
  const lastPacket = packets[packets.length - 1];
  return {
    placement: { turn_index: lastPacket?.placement.turn_index ?? 0 },
    obj: { type: PacketType.STOP, stop_reason: StopReason.USER_CANCELLED },
  };
}
