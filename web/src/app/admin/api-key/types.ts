import { UserRole } from "@/lib/types";

// Discord bot service API key name - should match backend constant
export const DISCORD_SERVICE_API_KEY_NAME = "discord-bot-service";

export interface APIKey {
  api_key_id: number;
  api_key_display: string;
  api_key: string | null;
  api_key_name: string | null;
  api_key_role: UserRole;
  user_id: string;
}

export interface APIKeyArgs {
  name?: string;
  role: UserRole;
}
