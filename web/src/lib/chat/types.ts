import type { Message } from "@/app/app/types";

export interface PendingChatMessage {
  id: string;
  message: string;
  delivery: "send" | "queue" | "interrupt";
  target_response_id: number | null;
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
  messages: PendingChatMessage[];
  error: string | null;
  /** A pending-message request is in flight. */
  busy: boolean;
  hasActiveSubagents: boolean;
  /** The response new input targets; null lets the server pick the running one. */
  targetResponseId: number | null;
  needsResponseSelection: boolean;
  submit: (
    message: string,
    delivery: PendingChatMessage["delivery"]
  ) => Promise<boolean>;
  withdraw: (id: string) => Promise<PendingChatMessage | null>;
  interrupt: (id: string) => Promise<void>;
}
