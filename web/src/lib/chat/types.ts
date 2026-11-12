import type { Message } from "@/app/app/types";

export interface PendingChatMessage {
  id: string;
  message: string;
  delivery: "send" | "queue" | "interrupt";
  target_response_id: number | null;
  deep_research: boolean;
}

export interface ChatHistoryPage {
  messageTree: Map<number, Message>;
  hasOlderMessages: boolean;
}

export interface ChatSessionStatus {
  is_processing: boolean;
  current_stream: { stream_id: number } | null;
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
  /** New input has a saved response to target. */
  hasTargetResponse: boolean;
  needsResponseSelection: boolean;
  /** `deepResearch` starts a queued or interrupting message's turn as Deep Research. */
  submit: (
    message: string,
    delivery: PendingChatMessage["delivery"],
    deepResearch: boolean
  ) => Promise<boolean>;
  withdraw: (id: string) => Promise<PendingChatMessage | null>;
  interrupt: (id: string) => Promise<void>;
}
