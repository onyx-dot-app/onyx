import { SearchDoc } from "@/chat/contracts/documents";

export type ImageShape = "square" | "landscape" | "portrait";

export type JsonValue =
  string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

export interface CustomToolErrorInfo {
  is_auth_error: boolean;
  status_code: number;
  message: string;
}

export interface GeneratedImage {
  file_id: string;
  url: string;
  revised_prompt: string;
  shape?: ImageShape;
}

export interface SearchResult {
  type: "search_result";
  queries: string[];
  sources: string[];
  time_filter_start: string | null;
  time_filter_end: string | null;
  search_docs: SearchDoc[];
  displayed_docs: SearchDoc[] | null;
  citation_mapping: Record<number, string>;
}
export interface FileReadResult {
  type: "file_read_result";
  file_name: string;
  file_id: string;
  start_char: number;
  end_char: number;
  total_chars: number;
  preview_start: string;
  preview_end: string;
}
export interface MemoryResult {
  type: "memory_result";
  memory_text: string;
  operation: "add" | "update";
  memory_id: number | null;
  index: number | null;
}
export interface PythonExecutionResult {
  type: "python_execution";
  stdout: string;
  stderr: string;
  exit_code: number | null;
  timed_out: boolean;
  generated_files: { filename: string; file_link: string }[];
  error: string | null;
  staging_notice: string | null;
}
export interface BashExecutionResult {
  type: "bash_execution";
  stdout: string;
  stderr: string;
  exit_code: number | null;
  timed_out: boolean;
  error: string | null;
}
export interface CustomToolResult {
  type: "custom_tool_result";
  tool_name: string;
  response_type: string;
  tool_result: JsonValue;
  error: CustomToolErrorInfo | null;
}
export type ToolMetadata =
  | SearchResult
  | FileReadResult
  | MemoryResult
  | PythonExecutionResult
  | BashExecutionResult
  | CustomToolResult
  | { type: "image_generation_result"; generated_images: GeneratedImage[] }
  | { type: "coding_result"; answer: string }
  | {
      type: "research_result";
      intermediate_report: string;
      citation_mapping: Record<number, SearchDoc>;
    };

/** Timeline positions. A presentation turn can cover one part of an SDK step. */
export interface Placement {
  turn_index: number;
  tab_index?: number; // For parallel tool calls - tools with same turn_index but different tab_index run in parallel
  sub_turn_index?: number | null;
  model_index?: number | null; // For multi-model answer generation - identifies which model produced this packet
}

export interface PacketIdentity {
  agent_id?: string | null;
  agent_path?: string | null;
  response_id: number;
  run_id: string;
  message_id: string;
  parent_run_id?: string | null;
  parent_message_id?: string | null;
  parent_tool_call_id?: string | null;
  tool_call_id?: string | null;
  part_id: string;
}

export type RunStatus =
  "running" | "complete" | "limit" | "cancelled" | "error";
export type TextPurpose = "answer" | "plan" | "report" | "commentary";

export interface CitationInfo {
  citation_number: number;
  document_id: string;
}

export interface TextItem {
  kind: "text";
  text: string;
  status: RunStatus;
  purpose: TextPurpose;
  documents: SearchDoc[];
  citations: CitationInfo[];
  pre_answer_seconds?: number | null;
}

export interface ReasoningItem {
  kind: "reasoning";
  text: string;
  status: RunStatus;
}

export interface ToolItem {
  kind: "tool";
  name: string;
  arguments: Record<string, JsonValue>;
  status: RunStatus | "pending";
  tool_id?: number | null;
  output: string;
  metadata: ToolMetadata | null;
}

export type ChatItem = TextItem | ReasoningItem | ToolItem;

export interface ItemUpdate {
  type: "item_update";
  item: ChatItem;
}

export interface ItemDelta {
  type: "item_delta";
  delta:
    | { kind: "text"; text: string; citations: CitationInfo[] }
    | {
        kind: "tool_arguments";
        name: string;
        arguments: Record<string, string>;
      }
    | {
        kind: "tool_output";
        output?: string | null;
        metadata?: ToolMetadata | null;
      };
}

export enum StopReason {
  FINISHED = "finished",
  USER_CANCELLED = "user_cancelled",
}

export type PacketObj =
  | ItemUpdate
  | ItemDelta
  | { type: "run_update"; status: RunStatus }
  | { type: "stop"; stop_reason?: StopReason | null }
  | { type: "chat_heartbeat" };

export interface Packet {
  identity?: PacketIdentity | null;
  model_index?: number | null;
  obj: PacketObj;
}

/** Current public content, after applying stream updates. */
export interface ResponseItem {
  identity: PacketIdentity;
  placement: Placement;
  content: ChatItem;
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
    model_index: lastPacket?.model_index,
    obj: { type: "stop", stop_reason: StopReason.USER_CANCELLED },
  };
}
