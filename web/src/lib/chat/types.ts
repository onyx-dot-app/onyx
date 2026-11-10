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
