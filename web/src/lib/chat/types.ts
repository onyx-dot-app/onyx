import type { Message } from "@/app/app/types";
import type { LLMOverride } from "@/app/app/services/lib";

/** Composer choices that a queued or interrupting message's turn starts with. */
export interface PendingTurnSettings {
  deepResearch: boolean;
  /** Null uses the chat's saved model. */
  llmOverride: LLMOverride | null;
}

export interface PendingChatMessage {
  id: string;
  message: string;
  delivery: "send" | "queue" | "interrupt";
  target_response_id: number | null;
  deep_research: boolean;
  llm_override: LLMOverride | null;
}

export interface ChatHistoryPage {
  messageTree: Map<number, Message>;
  hasOlderMessages: boolean;
}

export interface ChatSessionStatus {
  is_processing: boolean;
  current_stream: { stream_id: number } | null;
  has_active_subagents: boolean;
  /** Pending input can start a run now; false while the queue is paused. */
  has_startable_input: boolean;
  latest_response_id: number | null;
}

export interface ChatSessionQueue {
  /** False for incognito and anonymous chats, which have no server queue. */
  enabled: boolean;
  messages: PendingChatMessage[];
  error: string | null;
  /** A pending-message request is in flight. */
  busy: boolean;
  hasActiveSubagents: boolean;
  /** New input has a saved response to target. */
  hasTargetResponse: boolean;
  needsResponseSelection: boolean;
  /**
   * A queued or interrupting message's turn starts as Deep Research when
   * `deepResearch` is set, with `llmOverride` as its model.
   */
  submit: (
    message: string,
    delivery: PendingChatMessage["delivery"],
    turn: PendingTurnSettings
  ) => Promise<boolean>;
  withdraw: (id: string) => Promise<PendingChatMessage | null>;
  interrupt: (id: string) => Promise<void>;
}
