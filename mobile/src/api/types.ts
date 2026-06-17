// Shared API response types (mirrors web's src/lib/types.ts).
//
// Mobile-local and deliberately minimal — only the fields the app renders. Do
// not mirror web's larger `User` type. If web later shares a DTO for one of
// these via @onyx-ai/shared, reuse that instead (policy: extract-on-proven-reuse).
// Mirrors the backend UserRole enum (backend/onyx/auth/schemas.py) exactly — all
// 7 members. slack_user / ext_perm_user are non-web-login roles unlikely to reach
// a mobile session, but the type must not claim values the API can return are
// impossible (apiFetch casts the response without runtime validation).
export type UserRole =
  | "limited"
  | "basic"
  | "admin"
  | "curator"
  | "global_curator"
  | "slack_user"
  | "ext_perm_user";

export interface CurrentUser {
  id: string;
  email: string;
  role: UserRole;
  is_active: boolean;
}

// Mirrors the backend AuthType enum (backend/onyx/configs/constants.py).
// `cloud` = Google OAuth + basic email/password.
export type AuthType = "basic" | "google_oauth" | "oidc" | "saml" | "cloud";

// Mirrors AuthTypeResponse (backend/onyx/server/manage/models.py) — only the
// fields the mobile auth flow reads. Returned by the public `GET /api/auth/type`.
export interface AuthTypeMetadata {
  auth_type: AuthType;
  requires_verification: boolean;
  anonymous_user_enabled?: boolean | null;
  password_min_length: number;
  has_users: boolean;
  oauth_enabled: boolean;
}
