/**
 * Display Types
 *
 * Simple FIFO types for rendering streaming content.
 * Items are stored and rendered in chronological order as they arrive.
 */

export type ToolCallKind = "execute" | "read" | "other";
export type ToolCallStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "failed"
  | "cancelled";

export interface ToolCallState {
  id: string;
  kind: ToolCallKind;
  title: string;
  description: string; // "Listing output directory"
  command: string; // "ls outputs/"
  status: ToolCallStatus;
  rawOutput: string; // Full output for expanded view
}

/**
 * StreamItem - A single item in the FIFO stream.
 * These are stored in chronological order and rendered directly.
 */
export type StreamItem =
  | { type: "text"; id: string; content: string; isStreaming: boolean }
  | { type: "thinking"; id: string; content: string; isStreaming: boolean }
  | { type: "tool_call"; id: string; toolCall: ToolCallState };
