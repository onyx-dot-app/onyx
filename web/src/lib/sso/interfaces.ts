// Admin-side shapes for the SSO provider list, mirroring the backend response
// model. Secret `config` fields (client secret, SP private key) come back
// masked (bullets, or a truncated first4...last4 form) and are accepted back
// verbatim to keep the stored value. All other fields round-trip as real
// values.

export type SSOProviderType = "GOOGLE_OAUTH" | "OIDC" | "SAML";

export interface SSOProviderResponse {
  id: number;
  name: string;
  display_name: string;
  provider_type: SSOProviderType;
  enabled: boolean;
  allowed_email_domains: string[];
  config: Record<string, string | boolean | string[]>;
  redirect_uri: string;
}

export interface SSOProviderCreateRequest {
  name: string;
  display_name: string;
  provider_type: SSOProviderType;
  config: Record<string, string | boolean | string[]>;
  allowed_email_domains: string[];
}

export interface SSOProviderUpdateRequest {
  display_name?: string;
  allowed_email_domains?: string[];
  config?: Record<string, string | boolean | string[]>;
}
