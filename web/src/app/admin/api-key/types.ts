import { UserRole } from "@/lib/types";

export interface APIKey {
  api_key_id: number;
  api_key_display: string;
  api_key: string | null;
  api_key_name: string | null;
  api_key_role: UserRole;
  user_id: string;
  is_new_user: boolean;
}

export interface APIKeyArgs {
  name?: string;
  role?: UserRole;
  user_id?: string;
}
