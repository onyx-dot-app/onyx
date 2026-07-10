// Admin-side shapes for the SSO provider list. Mirrors the backend models in
// backend/onyx/server/manage/sso/models.py. `config` secrets come back masked
// (all-bullet placeholder) and are accepted back verbatim to keep the stored
// value.

export type SSOProviderType = "GOOGLE_OAUTH" | "OIDC" | "SAML";

export interface SSOProviderResponse {
  id: number;
  name: string;
  display_name: string;
  provider_type: SSOProviderType;
  enabled: boolean;
  allowed_email_domains: string[];
  config: Record<string, string>;
  redirect_uri: string;
}

export interface SSOProviderCreateRequest {
  name: string;
  display_name: string;
  provider_type: SSOProviderType;
  config: Record<string, string>;
  allowed_email_domains: string[];
}

export interface SSOProviderUpdateRequest {
  display_name?: string;
  allowed_email_domains?: string[];
  config?: Record<string, string>;
}
