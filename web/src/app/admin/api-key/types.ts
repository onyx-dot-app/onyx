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

export interface CreateAPIKeyArgs {
  type: ApiKeyType; // Required: PAT or Service Account
  name?: string; // Optional name
  role?: UserRole; // Required for Service Accounts, omitted for PATs
}

export interface UpdateAPIKeyArgs {
  name?: string; // Optional name
  role?: UserRole; // Optional, only valid for Service Accounts
}
