/**
 * Display Types
 *
 * Simple FIFO types for rendering streaming content.
 * Items are stored and rendered in chronological order as they arrive.
 */

export type ToolCallKind =
  | "search"
  | "read"
  | "execute"
  | "edit"
  | "task"
  | "other";

// =============================================================================
// Todo List Types (for TodoWrite tool)
// =============================================================================

export type TodoStatus = "pending" | "in_progress" | "completed";

export interface TodoItem {
  /** The task description */
  content: string;
  /** Current status */
  status: TodoStatus;
  /** Present tense form shown during execution (e.g., "Creating API endpoint") */
  activeForm: string;
}

export interface TodoListState {
  /** Tool call ID */
  id: string;
  /** Array of todo items */
  todos: TodoItem[];
  /** Whether the card is expanded (UI state only) */
  isOpen: boolean;
}
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
  description: string; // "Listing output directory" or task description
  command: string; // "ls outputs/" or task prompt for task kind
  status: ToolCallStatus;
  rawOutput: string; // Full output for expanded view
  /** For task tool calls: the subagent type (e.g., "explore", "plan") */
  subagentType?: string;
  /** For edit operations: whether this is a new file (write) or edit of existing */
  isNewFile?: boolean;
  /** For edit operations: the old content before the edit (empty for new files) */
  oldContent?: string;
  /** For edit operations: the new content after the edit */
  newContent?: string;
}

/**
 * StreamItem - A single item in the FIFO stream.
 * These are stored in chronological order and rendered directly.
 */
export type StreamItem =
  | { type: "text"; id: string; content: string; isStreaming: boolean }
  | { type: "thinking"; id: string; content: string; isStreaming: boolean }
  | { type: "tool_call"; id: string; toolCall: ToolCallState }
  | { type: "todo_list"; id: string; todoList: TodoListState };

/**
 * GroupedStreamItem - StreamItem after grouping transformation for rendering.
 * Consecutive working tool calls are grouped into a single "working_group" item.
 * Used by BuildMessageList to render consolidated Working pills.
 */
export type GroupedStreamItem =
  | { type: "text"; id: string; content: string; isStreaming: boolean }
  | { type: "thinking"; id: string; content: string; isStreaming: boolean }
  | { type: "tool_call"; id: string; toolCall: ToolCallState }
  | { type: "todo_list"; id: string; todoList: TodoListState }
  | { type: "working_group"; id: string; toolCalls: ToolCallState[] };
