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
  latest_response_id: number | null;
}

/** Local intent until the active response is acknowledged and its POST finishes. */
export interface PendingChatSubmission {
  message: PendingChatMessage;
  key: string;
  request: Promise<PendingChatMessage | null> | null;
  failed: boolean;
  finished: Promise<void>;
}
