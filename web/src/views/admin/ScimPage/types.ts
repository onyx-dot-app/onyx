export interface ScimTokenResponse {
  id: number;
  name: string;
  token_display: string;
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
  idp_domain: string | null;
}

export interface ScimTokenCreatedResponse extends ScimTokenResponse {
  raw_token: string;
}

export type ScimModalView =
  | { kind: "regenerate" }
  | { kind: "token"; rawToken: string };
