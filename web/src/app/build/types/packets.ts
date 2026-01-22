/**
 * ACP Packet Types
 *
 * These types represent the raw packets received from the backend via SSE.
 * They match the ACP (Agent Communication Protocol) specification.
 */

export interface TextContentBlock {
  type: "text";
  text: string;
}

export interface ImageContentBlock {
  type: "image";
  data: string;
  mimeType: string;
}

export type ContentBlock =
  | TextContentBlock
  | ImageContentBlock
  | Record<string, any>;

// Base ACP event fields
export interface ACPBaseEvent {
  field_meta?: Record<string, any> | null;
  timestamp: string;
}

// ACP: agent_message_chunk - Agent's text/content output
export interface AgentMessageChunkPacket extends ACPBaseEvent {
  type: "agent_message_chunk";
  content: ContentBlock;
  session_update?: string;
}

// ACP: agent_thought_chunk - Agent's internal reasoning
export interface AgentThoughtChunkPacket extends ACPBaseEvent {
  type: "agent_thought_chunk";
  content: ContentBlock;
  session_update?: string;
}

// ACP: tool_call_start - Tool invocation started
export interface ToolCallStartPacket extends ACPBaseEvent {
  type: "tool_call_start";
  tool_call_id: string;
  kind: "execute" | "read" | "other" | string | null;
  title: string | null;
  content: ContentBlock | null;
  locations: string[] | null;
  raw_input: {
    command?: string;
    description?: string;
    file_path?: string;
    filePath?: string;
    path?: string;
  } | null;
  raw_output: Record<string, any> | null;
  status: string | null;
  session_update?: string;
}

// ACP: tool_call_progress - Tool execution progress/completion
export interface ToolCallProgressPacket extends ACPBaseEvent {
  type: "tool_call_progress";
  tool_call_id: string;
  kind: "execute" | "read" | "other" | string | null;
  title: string | null;
  content: ContentBlock | null;
  locations: string[] | null;
  raw_input: {
    command?: string;
    description?: string;
    file_path?: string;
    filePath?: string;
    path?: string;
  } | null;
  raw_output: {
    output?: string;
    metadata?: {
      output?: string;
      diff?: string;
    };
  } | null;
  status: "pending" | "in_progress" | "completed" | "failed" | string | null;
  session_update?: string;
}

// ACP: agent_plan_update - Agent's execution plan
export interface AgentPlanUpdatePacket extends ACPBaseEvent {
  type: "agent_plan_update";
  entries: Array<{
    id: string;
    description: string;
    status: string;
    priority: string | number | null;
  }> | null;
  session_update?: string;
}

// ACP: current_mode_update - Agent mode change
export interface CurrentModeUpdatePacket extends ACPBaseEvent {
  type: "current_mode_update";
  current_mode_id: string | null;
  session_update?: string;
}

// ACP: prompt_response - Agent finished processing
export interface PromptResponsePacket extends ACPBaseEvent {
  type: "prompt_response";
  stop_reason: string | null;
}

// ACP: error - Error from ACP
export interface ACPErrorPacket {
  type: "error";
  code: string | null;
  message: string;
  data: Record<string, any> | null;
  timestamp: string;
}

// Union type for all ACP packets we care about for rendering
export type RawPacket =
  | AgentMessageChunkPacket
  | AgentThoughtChunkPacket
  | ToolCallStartPacket
  | ToolCallProgressPacket
  | AgentPlanUpdatePacket
  | CurrentModeUpdatePacket
  | PromptResponsePacket
  | ACPErrorPacket;
