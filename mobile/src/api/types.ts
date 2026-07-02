// Must list all 7 backend UserRole members: apiFetch casts without runtime
// validation, so the type can't claim API-returnable values are impossible.
export type UserRole =
  | "limited"
  | "basic"
  | "admin"
  | "curator"
  | "global_curator"
  | "slack_user"
  | "ext_perm_user";

// pinned_assistants drives the sidebar rail (null → featured fallback).
export interface UserPreferences {
  pinned_assistants?: number[] | null;
}

export interface CurrentUser {
  id: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  // `/me` always returns preferences; keep it required to surface a boundary mismatch rather
  // than silently treating malformed data as "no pinned assistants".
  preferences: UserPreferences;
}

// `cloud` = Google OAuth + basic email/password.
export type AuthType = "basic" | "google_oauth" | "oidc" | "saml" | "cloud";

export interface AuthTypeMetadata {
  auth_type: AuthType;
  requires_verification: boolean;
  anonymous_user_enabled?: boolean | null;
  password_min_length: number;
  has_users: boolean;
  oauth_enabled: boolean;
}
