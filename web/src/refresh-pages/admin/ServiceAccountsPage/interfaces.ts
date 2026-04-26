import type { UserGroupInfo } from "@/refresh-pages/admin/UsersPage/interfaces";

export const DISCORD_SERVICE_API_KEY_NAME = "discord-bot-service";

export interface APIKey {
  api_key_id: number;
  api_key_display: string;
  api_key: string | null;
  api_key_name: string | null;
  groups: UserGroupInfo[];
  user_id: string;
}

export interface APIKeyArgs {
  name?: string;
  group_ids: number[];
}
