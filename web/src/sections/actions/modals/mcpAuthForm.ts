import type { FormikErrors } from "formik";
import type { useTranslations } from "next-intl";
import {
  MCPAuthenticationType,
  MCPAuthenticationPerformer,
  MCPTransportType,
  MCPOAuthProviderMode,
  type MCPServer,
  type MCPAuthTemplate,
} from "@/lib/mcp/types";
import type { MCPAuthFormValues } from "@/sections/actions/modals/types";

function getTransportFromUrl(url: string): MCPTransportType {
  try {
    const pathname = new URL(url).pathname.toLowerCase().replace(/\/+$/, "");
    return pathname.endsWith("/sse")
      ? MCPTransportType.SSE
      : MCPTransportType.STREAMABLE_HTTP;
  } catch {
    return MCPTransportType.STREAMABLE_HTTP;
  }
}

export function validateMCPAuthCredentials(
  values: MCPAuthFormValues,
  t: ReturnType<typeof useTranslations<"actions">>
): FormikErrors<MCPAuthFormValues> {
  const missing = values.auth_template.required_fields.filter(
    (field) =>
      field !== "user_email" &&
      !(
        field === "api_key" &&
        values.auth_type === MCPAuthenticationType.API_TOKEN &&
        values.auth_performer === MCPAuthenticationPerformer.ADMIN
      ) &&
      !values.user_credentials[field]?.trim()
  );
  const errors: FormikErrors<MCPAuthFormValues> = missing.length
    ? {
        user_credentials: Object.fromEntries(
          missing.map((field) => [
            field,
            t("perUserAuth.credentialField.placeholder", {
              field: field.replace(/_/g, " "),
            }),
          ])
        ),
      }
    : {};
  if (
    values.auth_type === MCPAuthenticationType.API_TOKEN &&
    values.auth_performer === MCPAuthenticationPerformer.ADMIN &&
    !Object.values(values.auth_template.headers).some((value) =>
      value.includes("{api_key}")
    )
  ) {
    errors.auth_template = {
      required_fields: t("perUserAuth.headers.error.message", {
        apiKey: "{api_key}",
      }),
    };
  }
  return errors;
}

export function getRequiredHeaderFields(
  headers: Record<string, string>
): string[] {
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

export function getAuthTemplateForMethod(
  template: MCPAuthTemplate,
  authType: MCPAuthenticationType
): MCPAuthTemplate {
  const headers = { ...template.headers };
  if (
    authType === MCPAuthenticationType.API_TOKEN &&
    Object.keys(headers).length === 0
  ) {
    headers.Authorization = "Bearer {api_key}";
  } else if (
    authType !== MCPAuthenticationType.API_TOKEN &&
    headers.Authorization === "Bearer {api_key}"
  ) {
    delete headers.Authorization;
  }
  return { headers, required_fields: getRequiredHeaderFields(headers) };
}

export type MCPAuthSource = Pick<MCPServer, "server_url"> &
  Partial<
    Pick<
      MCPServer,
      | "transport"
      | "auth_type"
      | "auth_performer"
      | "admin_credentials"
      | "oauth_provider_mode"
      | "oauth_cimd_enabled"
      | "oauth_authorization_endpoint"
      | "oauth_token_endpoint"
      | "oauth_scopes_override"
      | "oauth_additional_auth_params"
      | "auth_template"
      | "user_credentials"
    >
  >;

export function getMCPAuthInitialValues(
  fullServer: MCPAuthSource
): MCPAuthFormValues {
  const sharedApiToken =
    fullServer.auth_type === MCPAuthenticationType.API_TOKEN &&
    fullServer.auth_performer === MCPAuthenticationPerformer.ADMIN;

  return {
    transport:
      fullServer.transport ?? getTransportFromUrl(fullServer.server_url),
    auth_type: fullServer.auth_type || MCPAuthenticationType.OAUTH,
    auth_performer:
      fullServer.auth_performer || MCPAuthenticationPerformer.PER_USER,
    api_token: fullServer.admin_credentials?.api_key || "",
    oauth_setup_mode:
      fullServer.admin_credentials?.client_id ||
      fullServer.admin_credentials?.client_secret ||
      fullServer.oauth_provider_mode === MCPOAuthProviderMode.KNOWN_PROVIDER
        ? "own_client"
        : "automatic",
    oauth_client_id: fullServer.admin_credentials?.client_id || "",
    oauth_client_secret: fullServer.admin_credentials?.client_secret || "",
    oauth_provider_mode:
      fullServer.oauth_provider_mode || MCPOAuthProviderMode.AUTO_DISCOVERY,
    oauth_cimd_enabled: fullServer.oauth_cimd_enabled ?? true,
    oauth_authorization_endpoint: fullServer.oauth_authorization_endpoint || "",
    oauth_token_endpoint: fullServer.oauth_token_endpoint || "",
    oauth_scopes_override: fullServer.oauth_scopes_override
      ? fullServer.oauth_scopes_override.join(", ")
      : "",
    oauth_additional_auth_params: fullServer.oauth_additional_auth_params
      ? JSON.stringify(fullServer.oauth_additional_auth_params)
      : "",
    auth_template:
      fullServer.auth_type === MCPAuthenticationType.API_TOKEN
        ? getAuthTemplateForMethod(
            fullServer.auth_template ?? { headers: {}, required_fields: [] },
            MCPAuthenticationType.API_TOKEN
          )
        : (fullServer.auth_template ?? { headers: {}, required_fields: [] }),
    user_credentials:
      fullServer.user_credentials ||
      (sharedApiToken ? fullServer.admin_credentials : undefined) ||
      {},
  };
}

export function computeOAuthChangedFlags(
  values: MCPAuthFormValues,
  initialValues: MCPAuthFormValues
) {
  if (values.auth_type !== MCPAuthenticationType.OAUTH) {
    return {
      oauth_client_id_changed: false,
      oauth_client_secret_changed: false,
    };
  }
  return {
    oauth_client_id_changed:
      values.oauth_client_id !== initialValues.oauth_client_id,
    oauth_client_secret_changed:
      values.oauth_client_secret !== initialValues.oauth_client_secret,
  };
}

export class MCPAuthValidationError extends Error {}

export function prepareMCPAuthPayload(
  values: MCPAuthFormValues,
  initialValues: MCPAuthFormValues,
  t: ReturnType<typeof useTranslations<"actions">>
) {
  const computeAdminCredentialsChangedFlags = (values: MCPAuthFormValues) => {
    if (!values.auth_template.required_fields.length) {
      return {};
    }
    const current = values.user_credentials || {};
    const initial = initialValues.user_credentials || {};
    const flags: Record<string, boolean> = {};
    for (const key of Object.keys(current)) {
      flags[key] = current[key] !== initial[key];
    }
    return flags;
  };

  const computeAuthTemplateChangedFlags = (values: MCPAuthFormValues) => {
    const initialHeaders = initialValues.auth_template.headers;
    return Object.fromEntries(
      Object.entries(values.auth_template.headers).map(([name, value]) => [
        name,
        value !== initialHeaders[name],
      ])
    );
  };

  const authType = values.auth_type;
  const oauthChangedFlags = computeOAuthChangedFlags(values, initialValues);
  const hasUserHeaderValues = values.auth_template.required_fields.some(
    (field) =>
      !(
        values.auth_performer === MCPAuthenticationPerformer.ADMIN &&
        authType === MCPAuthenticationType.API_TOKEN &&
        field === "api_key"
      )
  );
  const isAdminApiToken =
    values.auth_performer === MCPAuthenticationPerformer.ADMIN &&
    authType === MCPAuthenticationType.API_TOKEN;
  const isKnownProviderOauth =
    authType === MCPAuthenticationType.OAUTH &&
    values.oauth_provider_mode === MCPOAuthProviderMode.KNOWN_PROVIDER;

  const parsedScopes = values.oauth_scopes_override
    .split(",")
    .map((scope) => scope.trim())
    .filter(Boolean);

  let parsedAdditionalAuthParams: Record<string, string> | undefined;
  if (
    isKnownProviderOauth &&
    values.oauth_additional_auth_params &&
    values.oauth_additional_auth_params.trim()
  ) {
    try {
      const parsed: unknown = JSON.parse(values.oauth_additional_auth_params);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error(t("mcpAuthModal.errors.additionalParamsNotObject"));
      }
      parsedAdditionalAuthParams = Object.fromEntries(
        Object.entries(parsed).map(([key, value]) => [key, String(value)])
      );
    } catch (error) {
      throw new MCPAuthValidationError(
        error instanceof Error
          ? t("mcpAuthModal.errors.additionalParamsInvalidWithReason", {
              reason: error.message,
            })
          : t("mcpAuthModal.errors.additionalParamsInvalid")
      );
    }
  }

  return {
    transport: values.transport,
    auth_type: values.auth_type,
    auth_performer: values.auth_performer,
    api_token: isAdminApiToken ? values.api_token : undefined,
    api_token_changed: isAdminApiToken
      ? values.api_token !== initialValues.api_token
      : false,
    auth_template: values.auth_template,
    auth_template_headers_changed: computeAuthTemplateChangedFlags(values),
    admin_credentials: hasUserHeaderValues
      ? Object.fromEntries(
          Object.entries(values.user_credentials || {}).filter(
            ([field]) => !isAdminApiToken || field !== "api_key"
          )
        )
      : undefined,
    admin_credentials_changed: hasUserHeaderValues
      ? computeAdminCredentialsChangedFlags(values)
      : undefined,
    oauth_client_id:
      authType === MCPAuthenticationType.OAUTH
        ? values.oauth_client_id
        : undefined,
    oauth_client_secret:
      authType === MCPAuthenticationType.OAUTH
        ? values.oauth_client_secret
        : undefined,
    oauth_provider_mode:
      authType === MCPAuthenticationType.OAUTH
        ? values.oauth_provider_mode
        : undefined,
    oauth_cimd_enabled:
      authType === MCPAuthenticationType.OAUTH
        ? values.oauth_cimd_enabled
        : undefined,
    oauth_authorization_endpoint: isKnownProviderOauth
      ? values.oauth_authorization_endpoint
      : undefined,
    oauth_token_endpoint: isKnownProviderOauth
      ? values.oauth_token_endpoint
      : undefined,
    oauth_scopes_override:
      isKnownProviderOauth && parsedScopes.length > 0
        ? parsedScopes
        : undefined,
    oauth_additional_auth_params:
      isKnownProviderOauth && parsedAdditionalAuthParams
        ? parsedAdditionalAuthParams
        : undefined,
    ...oauthChangedFlags,
  };
}
