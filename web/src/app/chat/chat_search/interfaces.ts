import { ChatSessionSharedStatus } from "../interfaces";

export interface ChatSessionSummary {
  id: string;
  name: string | null;
  persona_id: number | null;
  time_created: string;
  shared_status: ChatSessionSharedStatus;
  current_alternate_model: string | null;
  current_temperature_override: number | null;
  highlights?: string[];
}

export interface ChatSessionGroup {
  title: string;
  chats: ChatSessionSummary[];
}

export interface ChatSessionsResponse {
  sessions: ChatSessionSummary[];
}

export interface ChatSearchResponse {
  groups: ChatSessionGroup[];
  has_more: boolean;
  next_page: number | null;
}

export interface ChatSearchRequest {
  query?: string;
  page?: number;
  page_size?: number;
}
