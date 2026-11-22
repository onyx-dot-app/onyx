import { OnyxDocument } from "@/lib/search/types";
import type { RecordedMention } from "@/lib/chat/types";

// Base interface for all streaming objects
interface BaseObj {
  type: string;
}

export enum PacketType {
  USER_MESSAGE = "user_message",
  MESSAGE_START = "message_start",
  MESSAGE_DELTA = "message_delta",
  MESSAGE_END = "message_end",

  STOP = "stop",
  SECTION_END = "section_end",
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
  FETCH_TOOL_START = "open_url_start",
  FETCH_TOOL_URLS = "open_url_urls",
  FETCH_TOOL_DOCUMENTS = "open_url_documents",

  // Tool call argument delta (streams tool args before tool executes)
  TOOL_CALL_ARGUMENT_DELTA = "tool_call_argument_delta",
  TOOL_CALL_DEBUG = "tool_call_debug",

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
  POSTGRES_TOOL_START = "postgres_tool_start",
  POSTGRES_TOOL_DOCUMENTS = "postgres_tool_documents",

  // Reasoning packets
  REASONING_START = "reasoning_start",
  REASONING_DELTA = "reasoning_delta",
  REASONING_DONE = "reasoning_done",

  // Citation packets
  CITATION_START = "citation_start",
  CITATION_END = "citation_end",
  // Backend sends individual citation_info packets during streaming
  CITATION_INFO = "citation_info",

  // Deep Research packets
  DEEP_RESEARCH_PLAN_START = "deep_research_plan_start",
  DEEP_RESEARCH_PLAN_DELTA = "deep_research_plan_delta",
  RESEARCH_AGENT_START = "research_agent_start",
  INTERMEDIATE_REPORT_START = "intermediate_report_start",
  INTERMEDIATE_REPORT_DELTA = "intermediate_report_delta",
  INTERMEDIATE_REPORT_CITED_DOCS = "intermediate_report_cited_docs",

  // Sandbox tool packets: exec_command and write_stdin share the output and
  // end packets
  EXEC_COMMAND_START = "exec_command_start",
  WRITE_STDIN_START = "write_stdin_start",
  EXEC_OUTPUT_DELTA = "exec_output_delta",
  EXEC_END = "exec_end",
  FILE_TOOL_PROGRESS = "file_tool_progress",
  APPLY_PATCH_START = "apply_patch_start",
  APPLY_PATCH_END = "apply_patch_end",
  PUBLISH_FILES_START = "publish_files_start",
  PUBLISH_FILES_END = "publish_files_end",

  // Code mode packets: one program that calls other tools. The nested calls
  // stream their own tool packets at the same placement with sub_turn_index.
  CODE_MODE_START = "code_mode_start",
  CODE_MODE_DELTA = "code_mode_delta",

  // Tool call approvals: the run waits for the user's decision on a request
  TOOL_APPROVAL_REQUEST = "tool_approval_request",
  TOOL_APPROVAL_RESOLVED = "tool_approval_resolved",

  // Questions: the run waits for the user's answers to a question call
  TOOL_QUESTION_REQUEST = "tool_question_request",
  TOOL_QUESTION_RESOLVED = "tool_question_resolved",
}

export const CODE_INTERPRETER_TOOL_TYPES = {
  // Legacy LLM-facing name; still present in sessions persisted before the
  // rename (OpenAI reserves the function name "python" and rejects it).
  PYTHON: "python",
  RUN_PYTHON: "run_python",
} as const;

export const isCodeInterpreterToolType = (toolType: string): boolean =>
  (Object.values(CODE_INTERPRETER_TOOL_TYPES) as string[]).includes(toolType);

// tool_type of the argument deltas that stream a code mode program
export const CODE_MODE_TOOL_TYPE = "execute_code";

// Basic Message Packets
export interface UserMessage extends BaseObj {
  type: "user_message";
  id: string;
  message: string;
  mentions: RecordedMention[];
}

export interface MessageStart extends BaseObj {
  id: string;
  type: "message_start";
  content: string;

  final_documents: OnyxDocument[] | null;
  pre_answer_processing_seconds?: number;
}

export interface MessageDelta extends BaseObj {
  content: string;
  type: "message_delta";
}

export interface MessageEnd extends BaseObj {
  type: "message_end";
}

// Control Packets
export enum StopReason {
  FINISHED = "finished",
  USER_CANCELLED = "user_cancelled",
  /** The turn reached its execution deadline. */
  TIMED_OUT = "timed_out",
  /** The stream ended while tool calls wait for the user: approval decisions
   * or answers to questions. The response continues in a new stream after
   * them. */
  AWAITING_USER = "awaiting_user",
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

// Specific tool packets
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
  // Connector/source values this search is scoped to (empty == all)
  sources: string[];
  // Applied time window as ISO datetime strings; either bound may be open-ended
  time_filter_start?: string | null;
  time_filter_end?: string | null;
}

export interface SearchToolDocumentsDelta extends BaseObj {
  type: "search_tool_documents_delta";
  documents: OnyxDocument[];
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
  documents: OnyxDocument[];
}

// Custom Tool Packets
export interface CustomToolErrorInfo {
  is_auth_error: boolean;
  is_unreachable: boolean;
  status_code: number | null;
  message: string;
}

export interface CustomToolStart extends BaseObj {
  type: "custom_tool_start";
  // The name the model calls; custom and MCP tools use a qualified name.
  tool_name: string;
  // The name users see.
  display_name: string;
  tool_id?: number | null;
}

export interface CustomToolArgs extends BaseObj {
  type: "custom_tool_args";
  tool_name: string;
  tool_args: Record<string, any>;
}

export interface CustomToolDelta extends BaseObj {
  type: "custom_tool_delta";
  tool_name: string;
  tool_id?: number | null;
  response_type: string;
  data?: any;
  file_ids?: string[] | null;
  error?: CustomToolErrorInfo | null;
}

// File Reader Packets
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
// Memory Tool Packets
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

// Postgres Tool Packets
// The arguments of a postgres_query call, as the model sent them.
export type PostgresToolQueryValue = string | number | boolean | null;
export interface PostgresToolQuery {
  table?: PostgresToolQueryValue;
  count?: PostgresToolQueryValue;
  group_by?: PostgresToolQueryValue;
  limit?: PostgresToolQueryValue;
  cursor?: PostgresToolQueryValue;
  source_type?: PostgresToolQueryValue;
  title_contains?: PostgresToolQueryValue;
  description_contains?: PostgresToolQueryValue;
  name_contains?: PostgresToolQueryValue;
  content_contains?: PostgresToolQueryValue;
  updated_after?: PostgresToolQueryValue;
  updated_before?: PostgresToolQueryValue;
  created_after?: PostgresToolQueryValue;
  created_before?: PostgresToolQueryValue;
  sent_after?: PostgresToolQueryValue;
  sent_before?: PostgresToolQueryValue;
  owned_by?: PostgresToolQueryValue;
  parent_hierarchy_node_id?: PostgresToolQueryValue;
  parent_id?: PostgresToolQueryValue;
  node_type?: PostgresToolQueryValue;
  message_type?: PostgresToolQueryValue;
  chat_message_id?: PostgresToolQueryValue;
  cited_only?: PostgresToolQueryValue;
}

export interface PostgresToolStart extends BaseObj {
  type: "postgres_tool_start";
  // The call's arguments, for the step's query summary.
  query?: PostgresToolQuery;
}

export interface PostgresToolDocuments extends BaseObj {
  type: "postgres_tool_documents";
  documents: OnyxDocument[];
}

// Reasoning Packets
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

// Citation Packets
export interface StreamingCitation {
  citation_num: number;
  document_id: string;
}

export interface CitationStart extends BaseObj {
  type: "citation_start";
}

// Individual citation info packet (sent during streaming from backend)
export interface CitationInfo extends BaseObj {
  type: "citation_info";
  citation_number: number;
  document_id: string;
}

// Deep Research Plan Packets
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
  cited_docs: OnyxDocument[] | null;
}

// Sandbox Tool Packets
export interface ExecCommandStart extends BaseObj {
  type: "exec_command_start";
  cmd: string;
  workdir: string | null;
}

export interface WriteStdinStart extends BaseObj {
  type: "write_stdin_start";
  session_id: string;
  // Empty when the call only polls the session for output
  chars: string;
}

// Live stdout and stderr in arrival order: a preview that exec_end's output
// replaces. A replay sends no deltas.
export interface ExecOutputDelta extends BaseObj {
  type: "exec_output_delta";
  text: string;
}

export type ExecCompletion =
  | "exited"
  | "signaled"
  | "canceled"
  | "deadline_exceeded";

export interface ExecEnd extends BaseObj {
  type: "exec_end";
  exit_code: number | null;
  completion: ExecCompletion | null;
  // Set while the process keeps running after the call returned
  session_id: string | null;
  wall_time_seconds: number | null;
  truncated: boolean;
  // The saved output the model saw (head and tail when cut to its character
  // budget), or, when the output went to the sandbox VM, its head and tail
  // with a plain note; null only with error
  output: string | null;
  // Set when the call failed and has no process result
  error: string | null;
}

// The names of the backend's file tools (sandbox_tools.py)
export type FileToolName = "apply_patch" | "edit" | "write";

// What a file tool call's arguments hold while the model streams them; the
// call's start packet follows
export interface FileToolProgress extends BaseObj {
  type: "file_tool_progress";
  tool_name: FileToolName;
  // The files the arguments name so far, in order
  paths: string[];
}

export interface ApplyPatchStart extends BaseObj {
  type: "apply_patch_start";
  patch: string;
  // The file tool that made the change; it names the card
  tool_name: FileToolName;
}

export interface ApplyPatchFileChange {
  path: string;
  change: "add" | "update" | "delete";
  move_path: string | null;
}

export interface ApplyPatchEnd extends BaseObj {
  type: "apply_patch_end";
  files: ApplyPatchFileChange[];
  error: string | null;
}

// A file that a publish_files call asks for, as the model wrote it
export interface PublishFileArgument {
  path: string;
  title: string | null;
}

export interface PublishFilesStart extends BaseObj {
  type: "publish_files_start";
  // Empty when the call's arguments are not valid
  files: PublishFileArgument[];
  description: string | null;
}

// A file that publish_files copied from the sandbox; it downloads from
// /api/chat/file/{file_id}
export interface PublishedFile {
  file_id: string;
  // The file name, which the download keeps
  name: string;
  title: string | null;
  // Absolute and normalized in the sandbox
  path: string;
  // The path to show: relative to the chat's working directory, or the whole
  // path outside it
  display_path: string;
  size: number;
  mime_type: string;
  // The artifact: every publish of one path in the chat. Null in details
  // saved without it; such a file is its own artifact.
  artifact_id: string | null;
  // The publish's number in its artifact, from 1. Null with artifact_id.
  version: number | null;
  // A JPEG of the first page of a PDF, PowerPoint or Word file that rendered
  // when it was published, from /api/chat/file/{thumbnail_file_id}
  thumbnail_file_id: string | null;
}

export interface PublishFilesEnd extends BaseObj {
  type: "publish_files_end";
  // In the order of the start's files; empty when the call failed
  files: PublishedFile[];
  error: string | null;
}

// Code Mode Packets
export type CodeModeStatus =
  | "running"
  | "completed"
  | "failed"
  | "timed_out"
  | "terminated"
  | "cancelled";

export interface CodeModeStart extends BaseObj {
  type: "code_mode_start";
  // Empty on later observations of a cell
  code: string;
  // From the call arguments: null for execute_code, whose cell gets its id when it runs
  cell_id?: number | null;
  // 0 starts a cell (execute_code); 1 continues one (wait_code)
  observation?: number;
}

export interface CodeModeDelta extends BaseObj {
  type: "code_mode_delta";
  // Appended to the stdout of earlier deltas, or replaces it when replace_stdout is set
  stdout: string;
  // Set on a final delta whose saved stdout differs from the streamed stdout
  replace_stdout?: boolean;
  result?: string | null;
  error?: string | null;
  // Set only on the final delta
  status?: CodeModeStatus | null;
  duration_seconds?: number | null;
  tool_call_count?: number | null;
  // Keys the program saved with store(); set only on the final delta
  stored_keys?: string[] | null;
  // Exact cell and observation; set only on the final delta
  cell_id?: number | null;
  observation?: number | null;
  // Set on the closing record of a cell that ran past its last observation
  response_ended?: boolean;
}

export type ChatObj = MessageStart | MessageDelta | MessageEnd;

export type StopObj = Stop;

// Connection keepalive emitted during silent stretches; carries no run state
export interface ChatHeartbeat extends BaseObj {
  type: "chat_heartbeat";
}

export type ChatHeartbeatObj = ChatHeartbeat;

// Ends the replayed prefix of a continuation stream; carries no run state
export interface ReplayEnd extends BaseObj {
  type: "replay_end";
}

export type SectionEndObj = SectionEnd;

export type PacketErrorObj = PacketError;

// Specific tool objects
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
export type ExecToolObj =
  | ExecCommandStart
  | WriteStdinStart
  | ExecOutputDelta
  | ExecEnd
  | SectionEnd
  | PacketError;
export type ApplyPatchToolObj =
  | FileToolProgress
  | ApplyPatchStart
  | ApplyPatchEnd
  | SectionEnd
  | PacketError;
export type PostgresToolObj =
  | PostgresToolStart
  | PostgresToolDocuments
  | SectionEnd
  | PacketError;
export type PublishFilesToolObj =
  | PublishFilesStart
  | PublishFilesEnd
  | SectionEnd
  | PacketError;
export type NewToolObj =
  | SearchToolObj
  | ImageGenerationToolObj
  | PythonToolObj
  | FetchToolObj
  | CustomToolObj
  | FileReaderToolObj
  | MemoryToolObj
  | ExecToolObj
  | ApplyPatchToolObj
  | PostgresToolObj
  | PublishFilesToolObj;

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

// Nested tool packets of a code mode group are in NewToolObj
export type CodeModeObj =
  | CodeModeStart
  | CodeModeDelta
  | ToolCallArgumentDelta
  | SectionEnd
  | PacketError;

export interface ToolCallDebug extends BaseObj {
  type: "tool_call_debug";
  tool_call_id: string;
  tool_name: string;
  tool_args: Record<string, unknown>;
}

// Tool Approval Packets
export interface ToolApprovalRequest extends BaseObj {
  type: "tool_approval_request";
  approval_id: string;
  tool_call_id: string;
  tool_name: string;
  display_name: string;
  arguments: Record<string, unknown>;
  /** The background subagent that made the request; null for the reply's own
   * calls. Such a request waits on its own: no stop of the reply closes it. */
  agent_name: string | null;
}

export interface ToolApprovalResolved extends BaseObj {
  type: "tool_approval_resolved";
  approval_id: string;
  // "approved_for_chat": approved by a grant for the chat's later calls of the
  // tool. "disabled": an approval found the tool disabled, so the call did not
  // run. "cancelled": the call stopped waiting because its run or cell stopped.
  outcome:
    | "approved"
    | "approved_for_chat"
    | "rejected"
    | "disabled"
    | "cancelled";
}

export type ToolApprovalObj = ToolApprovalRequest | ToolApprovalResolved;

// Question Packets
export interface ToolQuestionOption {
  label: string;
  description: string;
}

export interface ToolQuestion {
  id: string;
  /** A short label, at most 12 characters. */
  header: string;
  question: string;
  /** In the model's order; a recommended option comes first. */
  options: ToolQuestionOption[];
}

/** The user's answer to one question: a listed option, a note, or both. */
export interface ToolQuestionAnswer {
  question_id: string;
  option_label?: string | null;
  user_note?: string | null;
}

/** A question call waits for the user's answers; placed at the call. */
export interface ToolQuestionRequest extends BaseObj {
  type: "tool_question_request";
  question_request_id: string;
  tool_call_id: string;
  questions: ToolQuestion[];
}

/**
 * How a question call ended: answered on its card (`answers`) or by a message
 * that the user typed in the chat (`message`), or cancelled because its run
 * stopped first.
 */
export interface ToolQuestionResolved extends BaseObj {
  type: "tool_question_resolved";
  question_request_id: string;
  outcome: "answered" | "cancelled";
  answered_via?: "card" | "message" | null;
  answers?: ToolQuestionAnswer[] | null;
  message?: string | null;
}

export type ToolQuestionObj = ToolQuestionRequest | ToolQuestionResolved;

// Union type for all possible streaming objects
export type ObjTypes =
  | UserMessage
  | ToolCallDebug
  | ChatObj
  | NewToolObj
  | ReasoningObj
  | StopObj
  | ChatHeartbeatObj
  | ReplayEnd
  | SectionEndObj
  | CitationObj
  | DeepResearchPlanObj
  | ResearchAgentObj
  | CodeModeObj
  | ToolApprovalObj
  | ToolQuestionObj
  | PacketErrorObj
  | CitationObj;

// Placement interface for packet positioning
export interface Placement {
  turn_index: number;
  tab_index?: number; // For parallel tool calls - tools with same turn_index but different tab_index run in parallel
  sub_turn_index?: number | null;
  model_index?: number | null; // For multi-model answer generation - identifies which model produced this packet
}

// Packet wrapper for streaming objects
export interface Packet {
  placement: Placement;
  obj: ObjTypes;
}

export interface ChatPacket {
  placement: Placement;
  obj: ChatObj;
}

export interface StopPacket {
  placement: Placement;
  obj: StopObj;
}

export interface CitationPacket {
  placement: Placement;
  obj: CitationObj;
}

// New specific tool packet types
export interface SearchToolPacket {
  placement: Placement;
  obj: SearchToolObj;
}

export interface ImageGenerationToolPacket {
  placement: Placement;
  obj: ImageGenerationToolObj;
}

export interface PythonToolPacket {
  placement: Placement;
  obj: PythonToolObj;
}

export interface FetchToolPacket {
  placement: Placement;
  obj: FetchToolObj;
}

export interface CustomToolPacket {
  placement: Placement;
  obj: CustomToolObj;
}

export interface FileReaderToolPacket {
  placement: Placement;
  obj: FileReaderToolObj;
}
export interface ExecToolPacket {
  placement: Placement;
  obj: ExecToolObj;
}

export interface ApplyPatchToolPacket {
  placement: Placement;
  obj: ApplyPatchToolObj;
}

export interface PublishFilesToolPacket {
  placement: Placement;
  obj: PublishFilesToolObj;
}

export interface MemoryToolPacket {
  placement: Placement;
  obj: MemoryToolObj;
}

export interface PostgresToolPacket {
  placement: Placement;
  obj: PostgresToolObj;
}

export interface ReasoningPacket {
  placement: Placement;
  obj: ReasoningObj;
}

export interface SectionEndPacket {
  placement: Placement;
  obj: SectionEndObj;
}

export interface DeepResearchPlanPacket {
  placement: Placement;
  obj: DeepResearchPlanObj;
}

export interface ResearchAgentPacket {
  placement: Placement;
  obj: ResearchAgentObj;
}

/** Transport cursor for the complete packet prefix preceding this record. */
export interface StreamCursor {
  stream_id: number;
  next_cursor: number;
  replay_complete: boolean;
}
