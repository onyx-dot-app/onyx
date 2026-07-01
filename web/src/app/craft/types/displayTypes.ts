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

export type ToolCallName =
  | "glob"
  | "grep"
  | "read"
  | "write"
  | "edit"
  | "bash"
  | "task"
  | "todowrite"
  | "webfetch"
  | "websearch"
  // opencode 1.15.x additions:
  | "lsp"
  | "apply_patch"
  | "skill"
  | "list"
  | "question"
  | "invalid"
  | "unknown";

export interface ToolCallState {
  id: string;
  kind: ToolCallKind;
  /** Specific tool name (used to disambiguate within a kind, e.g. websearch vs grep) */
  toolName?: ToolCallName;
  title: string;
  description: string; // "Listing output directory" or task description
  command: string; // "ls outputs/" or task prompt for task kind
  status: ToolCallStatus;
  rawOutput: string; // Full output for expanded view
  /** For task tool calls: the subagent type (e.g., "explore", "plan") */
  subagentType?: string;
  /** For task tool calls: the subagent's final output once completed */
  taskOutput?: string;
  /** For skill-namespaced tool calls: the skill name (sans namespace prefix) */
  skillName?: string;
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
  | { type: "todo_list"; id: string; todoList: TodoListState }
  | {
      type: "connect_app_request";
      id: string;
      requestId: string;
      appSlug: string;
      reason: string | null;
    }
  | { type: "compaction"; id: string; summary: string | null }
  | { type: "error"; id: string; content: string };

export interface ContextUsage {
  usedTokens: number;
}

/**
 * Discriminated union of transient tabs that the side panel can render.
 *
 * Pinned tabs (Preview, Files, Artifacts) are handled separately via the
 * existing `OutputTabType` — they are not represented in `PanelTab`. Only
 * tabs that the user opens and closes dynamically (file viewers, etc.) live
 * here. Subagent transcripts are NOT panel tabs — they swap the main chat
 * column in place (see `viewedSubagentSessionId` in the store).
 *
 * Future view kinds: add a new variant here, render its chrome in
 * `OutputPanel.tsx`'s tab-row map, and its body in the panel body switch.
 */
export type PanelTab = { kind: "file"; path: string; fileName: string };

/**
 * Stable string ID for a `PanelTab`, namespaced by kind. Used as the value
 * of `activePanelTabId` in the store and as React keys for tab rendering.
 *
 * Format: "<kind>:<identifier>" — e.g. "file:web/src/app/page.tsx".
 */
export function panelTabId(tab: PanelTab): string {
  switch (tab.kind) {
    case "file":
      return `file:${tab.path}`;
    default: {
      const _exhaustive: never = tab.kind;
      throw new Error(`Unknown PanelTab kind: ${String(_exhaustive)}`);
    }
  }
}

// =============================================================================
// Subagent Types
// =============================================================================

export type SubagentStatus = "running" | "done" | "failed";

/**
 * A single conversation turn with a subagent. The initial dispatch is `turns[0]`;
 * each follow-up message the user sends appends a new turn.
 */
export interface SubagentTurn {
  /** The prompt for this turn (empty until seeded). */
  prompt: string;
  /** Tool calls emitted by the subagent during this turn, keyed by ToolCallState.id. */
  toolCalls: ToolCallState[];
  /** The subagent's reasoning stream for this turn (null until any arrives). */
  thinking: string | null;
  /** The subagent's response for this turn (null until complete). */
  response: string | null;
  /** FIFO stream items rendered with the same BuildMessageList path as parent chat. */
  streamItems: StreamItem[];
}

export interface SubagentState {
  /** Opencode session id of the child subagent. */
  sessionId: string;
  /** Tool call id of the parent `task` tool that spawned this subagent. */
  parentToolCallId: string;
  /** Subagent type (e.g. "explore", "plan"); null if unknown. */
  subagentType: string | null;
  /** Display name for the subagent. */
  name: string;
  status: SubagentStatus;
  /** Ordered conversation turns. The initial dispatch is `turns[0]`. */
  turns: SubagentTurn[];
  startedAt: number;
  completedAt: number | null;
}
