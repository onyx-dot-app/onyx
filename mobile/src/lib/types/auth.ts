// Shape of GET /auth/type — the server's auth-method advertisement the login screen
// branches on (mirrors the backend AuthTypeResponse in onyx/server/manage/models.py).

export type AuthType = "basic" | "google_oauth" | "oidc" | "saml" | "cloud";

export interface AuthTypeResponse {
  auth_type: AuthType;
  requires_verification: boolean;
  anonymous_user_enabled: boolean;
  password_min_length: number;
  has_users: boolean;
  oauth_enabled: boolean;
}
