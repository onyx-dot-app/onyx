import type {
  AdminIntegrationDetail,
  AuthMethod,
  AuthMode,
  IntegrationCreate,
  IntegrationShape,
  OAuthClientInput,
  OAuthProviderMode,
} from "@/lib/integrations/types";

/** A preset takes its methods from `IntegrationPreset.auth_methods`. */
export const SIGN_IN_METHODS: Record<
  Exclude<IntegrationShape, "preset">,
  readonly AuthMethod[]
> = {
  mcp_server: ["oauth2", "api_key", "onyx_login"],
  openapi: ["oauth2", "api_key", "onyx_login"],
  custom: ["api_key"],
};

export const PROVIDER_MODES: Record<
  IntegrationShape,
  readonly OAuthProviderMode[]
> = {
  mcp_server: ["manual", "discovery"],
  openapi: ["manual"],
  custom: ["manual"],
  preset: ["preset"],
};

export interface HeaderDraft {
  name: string;
  value: string;
}

export interface SignInDraft {
  authMode: AuthMode;
  authMethod: AuthMethod | null;
  /** The header template, one row for each header, in the order shown. */
  headers: HeaderDraft[];
  providerMode: OAuthProviderMode;
  authorizationUrl: string;
  tokenUrl: string;
  scopes: string;
  clientId: string;
  clientSecret: string;
  hasClientSecret: boolean;
  additionalParams: Record<string, string> | null;
  pkce: boolean | null;
}

export type SignInPayload = Pick<
  IntegrationCreate,
  "auth_mode" | "auth_method" | "header_template" | "oauth_client"
>;

export type SignInError =
  | "headerName"
  | "headerDuplicate"
  | "headerValue"
  | "authorizationUrl"
  | "tokenUrl"
  | "clientId";

export const DEFAULT_SIGN_IN: SignInDraft = {
  authMode: "none",
  authMethod: null,
  headers: [{ name: "Authorization", value: "Bearer {api_key}" }],
  providerMode: "manual",
  authorizationUrl: "",
  tokenUrl: "",
  scopes: "",
  clientId: "",
  clientSecret: "",
  hasClientSecret: false,
  additionalParams: null,
  pkce: null,
};

/** Without `user_email`. */
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

function headerTemplate(draft: SignInDraft): Record<string, string> {
  return Object.fromEntries(
    draft.headers.map((header) => [header.name.trim(), header.value])
  );
}

export function normalizedUrl(value: string): string | null {
  try {
    const url = new URL(value.trim());
    return url.protocol === "https:" || url.protocol === "http:"
      ? url.href
      : null;
  } catch {
    return null;
  }
}

export function parseUrlPatterns(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

export function signInErrors(draft: SignInDraft): SignInError[] {
  if (draft.authMode === "none") return [];
  const errors: SignInError[] = [];
  if (draft.authMethod === "api_key") {
    const names = draft.headers.map((header) =>
      header.name.trim().toLowerCase()
    );
    if (names.length === 0 || names.some((name) => !name))
      errors.push("headerName");
    else if (new Set(names).size !== names.length)
      errors.push("headerDuplicate");
    if (placeholders(headerTemplate(draft)).length === 0)
      errors.push("headerValue");
  }
  if (draft.authMethod === "oauth2" && draft.providerMode === "manual") {
    if (!normalizedUrl(draft.authorizationUrl)) errors.push("authorizationUrl");
    if (!normalizedUrl(draft.tokenUrl)) errors.push("tokenUrl");
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
          additional_params: draft.additionalParams,
          pkce: draft.pkce,
          client_id: draft.clientId.trim() || null,
          client_secret: draft.clientSecret || null,
        }
      : null;
  return {
    auth_mode: draft.authMode,
    auth_method: method,
    header_template: method === "api_key" ? headerTemplate(draft) : null,
    oauth_client: oauthClient,
  };
}

export function signInDraftFromDetail(
  detail: AdminIntegrationDetail
): SignInDraft {
  const saved = Object.entries(detail.header_template ?? {});
  const client = detail.oauth_client;
  const providerModes = PROVIDER_MODES[detail.shape];
  return {
    authMode: detail.auth_mode,
    authMethod: detail.auth_method,
    // An API key sign-in with no saved template shows an empty header, not
    // the default, so the form shows what the server has.
    headers: saved.length
      ? saved.map(([name, value]) => ({ name, value }))
      : detail.auth_method === "api_key"
        ? [{ name: "", value: "" }]
        : DEFAULT_SIGN_IN.headers,
    providerMode:
      client && providerModes.includes(client.provider_mode)
        ? client.provider_mode
        : (providerModes[0] ?? DEFAULT_SIGN_IN.providerMode),
    authorizationUrl: client?.authorization_url ?? "",
    tokenUrl: client?.token_url ?? "",
    scopes: client?.scopes?.join(" ") ?? "",
    clientId: client?.client_id ?? "",
    clientSecret: "",
    hasClientSecret: client?.has_client_secret ?? false,
    additionalParams: client?.additional_params ?? null,
    pkce: client?.pkce ?? null,
  };
}
