import { MASKED_OAUTH_CREDENTIAL } from "@/lib/oauth/config";
import type { OAuthConfig, ToolSnapshot } from "@/lib/tools/types";
import type { OpenAPIAuthFormValues } from "@/lib/plugins/openapi/types";

const DEFAULT_HEADERS = [{ key: "Authorization", value: "" }];

/** Auth form values for a new OpenAPI plugin: no authentication. */
export function newOpenApiAuthValues(): OpenAPIAuthFormValues {
  return {
    authMethod: "none",
    authorizationUrl: "",
    tokenUrl: "",
    clientId: "",
    clientSecret: "",
    scopes: "",
    supportsPkce: false,
    headers: DEFAULT_HEADERS.map((header) => ({ ...header })),
  };
}

/**
 * Auth form values for a saved OpenAPI plugin. Saved OAuth client
 * credentials show masked; they are never sent back to the browser.
 */
export function savedOpenApiAuthValues(
  tool: ToolSnapshot,
  oauthConfig: OAuthConfig | null
): OpenAPIAuthFormValues {
  const base = newOpenApiAuthValues();
  const headers = tool.custom_headers?.length
    ? tool.custom_headers.map((header) => ({ ...header }))
    : base.headers;
  if (tool.oauth_config_id) {
    const masked = oauthConfig?.has_client_credentials
      ? MASKED_OAUTH_CREDENTIAL
      : "";
    return {
      ...base,
      authMethod: "oauth",
      authorizationUrl: oauthConfig?.authorization_url ?? "",
      tokenUrl: oauthConfig?.token_url ?? "",
      clientId: masked,
      clientSecret: masked,
      scopes: oauthConfig?.scopes?.join(", ") ?? "",
      supportsPkce: oauthConfig?.supports_pkce ?? false,
      headers,
    };
  }
  if (tool.custom_headers?.length)
    return { ...base, authMethod: "custom-header", headers };
  if (tool.passthrough_auth) return { ...base, authMethod: "pt-oauth" };
  return { ...base, headers };
}
