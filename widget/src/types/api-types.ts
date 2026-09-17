/** Fields consumed by the embedded chat client from the public item stream. */
export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };
export type RunStatus =
  | "running"
  | "complete"
  | "cancelled"
  | "error"
  | "limit";
export interface CitationInfo {
  citation_number: number;
  document_id: string;
}
export interface ResolvedCitation extends CitationInfo {
  semantic_identifier?: string;
  link?: string;
}
export interface SearchDocument {
  document_id: string;
  semantic_identifier: string;
  title?: string;
  link?: string | null;
}
export type ToolMetadata =
  | {
      type: "search_result";
      search_docs: SearchDocument[];
      displayed_docs: SearchDocument[] | null;
    }
  | {
      type:
        | "custom_tool_result"
        | "file_read_result"
        | "memory_result"
        | "python_execution"
        | "bash_execution"
        | "image_generation_result"
        | "coding_result"
        | "research_result";
    };
export type ChatItem =
  | {
      kind: "text";
      text: string;
      purpose: "answer" | "commentary" | "plan" | "report";
      status: RunStatus;
      citations: CitationInfo[];
      documents: SearchDocument[];
    }
  | {
      kind: "reasoning";
      text: string;
      status: RunStatus;
    }
  | {
      kind: "tool";
      name: string;
      arguments: Record<string, JsonValue>;
      status: RunStatus | "pending";
      output: string;
      metadata: ToolMetadata | null;
    };
export interface Packet {
  model_index?: number | null;
  identity?: {
    message_id: string;
    part_id: string;
    parent_run_id?: string | null;
  } | null;
  user_message_id?: number | null;
  reserved_assistant_message_id?: number;
  error?: string;
  obj?:
    | { type: "item_update"; item: ChatItem }
    | {
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
    | { type: "run_update"; status: RunStatus }
    | { type: "stop"; stop_reason?: "finished" | "user_cancelled" | null }
    | { type: "chat_heartbeat" };
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  isStreaming?: boolean;
  citations?: ResolvedCitation[];
}

export interface ChatSession {
  id: string;
  created_at: string;
  updated_at: string;
  messages: Message[];
}

export interface SendMessageRequest {
  message: string;
  chat_session_id?: string;
  parent_message_id?: number | null;
  origin?: string;
  include_citations?: boolean;
}

export interface CreateSessionRequest {
  persona_id?: number;
}

export interface CreateSessionResponse {
  chat_session_id: string;
}
