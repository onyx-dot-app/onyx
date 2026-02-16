// Types matching backend Pydantic models

export interface DiscordBotConfig {
  configured: boolean;
  created_at: string | null;
}

export interface DiscordGuildConfig {
  id: number;
  guild_id: number | null;
  guild_name: string | null;
  registered_at: string | null;
  default_persona_id: number | null;
  enabled: boolean;
}

export interface DiscordGuildConfigCreateResponse {
  id: number;
  registration_key: string; // Shown once!
}

export type DiscordChannelType = "text" | "forum";

export interface DiscordChannelConfig {
  id: number;
  channel_id: number;
  channel_name: string;
  channel_type: DiscordChannelType;
  is_private: boolean;
  require_bot_invocation: boolean;
  thread_only_mode: boolean;
  persona_override_id: number | null;
  enabled: boolean;
}

export interface DiscordChannelConfigUpdate {
  require_bot_invocation: boolean;
  thread_only_mode: boolean;
  persona_override_id: number | null;
  enabled: boolean;
}

export interface DiscordGuildConfigUpdate {
  enabled: boolean;
  default_persona_id: number | null;
}
