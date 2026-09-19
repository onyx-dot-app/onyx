export interface QueryAnalytics {
  total_queries: number;
  total_likes: number;
  total_dislikes: number;
  date: string;
}

export interface UserAnalytics {
  total_active_users: number;
  date: string;
}

export interface OnyxBotAnalytics {
  total_queries: number;
  auto_resolved: number;
  date: string;
}

export interface PersonaMessageAnalytics {
  total_messages: number;
  date: string;
  persona_id: number;
}

export interface PersonaUniqueUserAnalytics {
  unique_users: number;
  date: string;
  persona_id: number;
}
