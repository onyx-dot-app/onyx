export interface OAuthProviderConsentInfo {
  client_name: string;
  redirect_origin: string;
  account_email: string;
  workspace_name: string;
  scopes: string[];
  csrf_token: string;
}

export interface OAuthProviderGrant {
  id: string;
  client_name: string;
  client_id: string;
  resource: string;
  scopes: string[];
  created_at: string;
  expires_at: string;
}

export type OAuthProviderDecision = "allow" | "deny";
