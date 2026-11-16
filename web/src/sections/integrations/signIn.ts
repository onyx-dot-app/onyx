import type {
  AdminIntegrationDetail,
  AuthMethod,
  AuthMode,
  CredentialField,
  IntegrationCreate,
  OAuthClientInput,
  OAuthProviderMode,
} from "@/lib/integrations/types";

/** Form state of the sign-in settings, shared by the add form and the
 * Configuration tab. */
export interface SignInDraft {
  authMode: AuthMode;
  authMethod: AuthMethod | null;
  headerName: string;
  headerValue: string;
  providerMode: OAuthProviderMode;
  authorizationUrl: string;
  tokenUrl: string;
  scopes: string;
  clientId: string;
  clientSecret: string;
  hasClientSecret: boolean;
}

export type SignInPayload = Pick<
  IntegrationCreate,
  | "auth_mode"
  | "auth_method"
  | "credential_fields"
  | "header_template"
  | "oauth_client"
>;

export type SignInError =
  | "headerName"
  | "headerValue"
  | "authorizationUrl"
  | "tokenUrl"
  | "clientId";

export const DEFAULT_SIGN_IN: SignInDraft = {
  authMode: "none",
  authMethod: null,
  headerName: "Authorization",
  headerValue: "Bearer {api_key}",
  providerMode: "manual",
  authorizationUrl: "",
  tokenUrl: "",
  scopes: "",
  clientId: "",
  clientSecret: "",
  hasClientSecret: false,
};

/** The `{placeholder}` names in header values, without `user_email`. */
function placeholders(headers: Record<string, string>): string[] {
  return [
    ...new Set(
      Object.values(headers).flatMap((value) =>
        [...value.matchAll(/\{([^}]+)\}/g)].flatMap((match) =>
          match[1] && match[1] !== "user_email" ? [match[1]] : []
        )
      )
    ),
  ];
}

function credentialFields(draft: SignInDraft): CredentialField[] {
  return placeholders({ [draft.headerName]: draft.headerValue }).map((key) => ({
    key,
    label: key.replace(/_/g, " "),
    secret: true,
  }));
}

function isUrl(value: string): boolean {
  try {
    const url = new URL(value.trim());
    return url.protocol === "https:" || url.protocol === "http:";
  } catch {
    return false;
  }
}

/** The fields that block a save, in form order. */
export function signInErrors(draft: SignInDraft): SignInError[] {
  if (draft.authMode === "none") return [];
  const errors: SignInError[] = [];
  if (draft.authMethod === "api_key") {
    if (!draft.headerName.trim()) errors.push("headerName");
    if (credentialFields(draft).length === 0) errors.push("headerValue");
  }
  if (draft.authMethod === "oauth2" && draft.providerMode === "manual") {
    if (!isUrl(draft.authorizationUrl)) errors.push("authorizationUrl");
    if (!isUrl(draft.tokenUrl)) errors.push("tokenUrl");
    if (!draft.clientId.trim()) errors.push("clientId");
  }
  return errors;
}

export function signInPayload(draft: SignInDraft): SignInPayload {
  const method = draft.authMode === "none" ? null : draft.authMethod;
  const oauthClient: OAuthClientInput | null =
    method === "oauth2"
      ? {
          provider_mode: draft.providerMode,
          authorization_url: draft.authorizationUrl.trim(),
          token_url: draft.tokenUrl.trim(),
          scopes: draft.scopes.trim()
            ? draft.scopes.split(/[\s,]+/).filter(Boolean)
            : null,
          additional_params: null,
          pkce: null,
          client_id: draft.clientId.trim() || null,
          client_secret: draft.clientSecret || null,
        }
      : null;
  return {
    auth_mode: draft.authMode,
    auth_method: method,
    credential_fields: method === "api_key" ? credentialFields(draft) : null,
    header_template:
      method === "api_key"
        ? { [draft.headerName.trim()]: draft.headerValue }
        : null,
    oauth_client: oauthClient,
  };
}

export function signInDraftFromDetail(
  detail: AdminIntegrationDetail
): SignInDraft {
  const [header] = Object.entries(detail.header_template ?? {});
  const client = detail.oauth_client;
  return {
    authMode: detail.auth_mode,
    authMethod: detail.auth_method,
    headerName: header?.[0] ?? DEFAULT_SIGN_IN.headerName,
    headerValue: header?.[1] ?? DEFAULT_SIGN_IN.headerValue,
    providerMode: client?.provider_mode ?? DEFAULT_SIGN_IN.providerMode,
    authorizationUrl: client?.authorization_url ?? "",
    tokenUrl: client?.token_url ?? "",
    scopes: client?.scopes?.join(" ") ?? "",
    clientId: client?.client_id ?? "",
    clientSecret: "",
    hasClientSecret: client?.has_client_secret ?? false,
  };
}
