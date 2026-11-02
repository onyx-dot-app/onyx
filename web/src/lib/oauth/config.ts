export const MASKED_OAUTH_CREDENTIAL = "********";

export interface OAuthConfigFields {
  authorizationUrl: string;
  tokenUrl: string;
  clientId: string;
  clientSecret: string;
  scopes: string;
  supportsPkce: boolean;
}

// Saving and testing must use the same settings and credential placeholders.
export function oauthConfigRequest(
  fields: OAuthConfigFields,
  isEditing: boolean
) {
  const credential = (value: string): string =>
    isEditing && value === MASKED_OAUTH_CREDENTIAL ? "" : value.trim();
  return {
    authorization_url: fields.authorizationUrl.trim(),
    token_url: fields.tokenUrl.trim(),
    client_id: credential(fields.clientId),
    client_secret: credential(fields.clientSecret),
    scopes: fields.scopes
      .split(",")
      .map((scope) => scope.trim())
      .filter(Boolean),
    supports_pkce: fields.supportsPkce,
  };
}
