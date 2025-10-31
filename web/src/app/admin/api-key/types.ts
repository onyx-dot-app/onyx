import { UserRole } from "@/lib/types";

export enum ApiKeyType {
  PERSONAL_ACCESS_TOKEN = "PERSONAL_ACCESS_TOKEN",
  SERVICE_ACCOUNT = "SERVICE_ACCOUNT",
}

export interface APIKey {
  api_key_id: number;
  api_key_display: string;
  api_key: string | null;
  api_key_name: string | null;
  api_key_role: UserRole;
  api_key_type: ApiKeyType;
  user_email: string;
  user_id: string;
}

export interface APIKeyArgs {
  name?: string; // Optional name
  type?: ApiKeyType; // Required for creating new API keys, optional/ignored when updating
  role?: UserRole; // Required for Service Accounts, omitted for Personal Access Tokens
}
