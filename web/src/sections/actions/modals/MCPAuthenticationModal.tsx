"use client";

import { useState, useMemo, useEffect } from "react";
import { useTranslations } from "next-intl";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import useSWR, { KeyedMutator } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { Modal } from "@opal/components";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";
import { Section } from "@/layouts/general-layouts";
import { FormField } from "@/refresh-components/form/FormField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import {
  Button,
  CopyButton,
  Divider,
  InputTypeIn,
  MessageCard,
  PasswordInputTypeIn,
  Tabs,
  Text,
} from "@opal/components";
import { markdown } from "@opal/utils";
import { Formik, Form, useFormikContext } from "formik";
import * as Yup from "yup";
import { useModal } from "@opal/components";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  MCPOAuthProviderMode,
  MCPTransportType,
  MCPServerStatus,
  MCPServer,
  MCPServersResponse,
  MCPAuthTemplate,
} from "@/lib/tools/types";
import { PerUserAuthConfig } from "@/sections/actions/PerUserAuthConfig";
import {
  getMCPUserOAuthNavigationUrl,
  MCPUserOAuthStartResponse,
  updateMCPServerStatus,
  upsertMCPServer,
} from "@/lib/tools/svc";
import { toast } from "@opal/layouts";
import { SvgArrowExchange } from "@opal/icons";
import { useOAuthPassThroughEnabled } from "@/lib/auth/hooks";

interface MCPAuthenticationModalProps {
  mcpServer: MCPServer | null;
  skipOverlay?: boolean;
  onTriggerFetchTools?: (serverId: number) => Promise<void> | void;
  mutateMcpServers: KeyedMutator<MCPServersResponse>;
}

export interface MCPAuthFormValues {
  transport: MCPTransportType;
  auth_type: MCPAuthenticationType;
  auth_performer: MCPAuthenticationPerformer;
  api_token: string;
  auth_template: MCPAuthTemplate;
  user_credentials: Record<string, string>;
  oauth_client_id: string;
  oauth_client_secret: string;
  oauth_provider_mode: MCPOAuthProviderMode;
  oauth_authorization_endpoint: string;
  oauth_token_endpoint: string;
  oauth_scopes_override: string;
  oauth_additional_auth_params: string;
}

const GOOGLE_AUTHORIZATION_ENDPOINT_HINT =
  "https://accounts.google.com/o/oauth2/v2/auth";
const GOOGLE_TOKEN_ENDPOINT_HINT = "https://oauth2.googleapis.com/token";

const getTransportFromUrl = (url: string): MCPTransportType => {
  const lowerUrl = url.toLowerCase();
  if (lowerUrl.endsWith("sse")) {
    return MCPTransportType.SSE;
  }
  return MCPTransportType.STREAMABLE_HTTP;
};

// Formik render props are plain callbacks, not components, so this effect
// lives in its own child to keep hook order stable.
function TransportAutoPopulate({ serverUrl }: { serverUrl?: string }) {
  const { setFieldValue } = useFormikContext<MCPAuthFormValues>();
  useEffect(() => {
    if (serverUrl) {
      setFieldValue("transport", getTransportFromUrl(serverUrl));
    }
  }, [serverUrl, setFieldValue]);
  return null;
}

export default function MCPAuthenticationModal({
  mcpServer,
  skipOverlay = false,
  onTriggerFetchTools,
  mutateMcpServers,
}: MCPAuthenticationModalProps) {
  const t = useTranslations("actions");
  const { isOpen, toggle } = useModal();
  const [activeAuthTab, setActiveAuthTab] = useState<"per-user" | "admin">(
    "per-user"
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Open the Advanced (known-provider) section by default when configured.
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const isOAuthEnabled = useOAuthPassThroughEnabled();

  const validationSchema = useMemo(
    () =>
      Yup.object().shape({
        transport: Yup.string()
          .oneOf([MCPTransportType.STREAMABLE_HTTP, MCPTransportType.SSE])
          .required(t("mcpAuthModal.transport.required")),
        auth_type: Yup.string()
          .oneOf([
            MCPAuthenticationType.NONE,
            MCPAuthenticationType.API_TOKEN,
            MCPAuthenticationType.OAUTH,
            MCPAuthenticationType.PT_OAUTH,
          ])
          .required(t("mcpAuthModal.authType.required")),
        auth_performer: Yup.string().when("auth_type", {
          is: (auth_type: string) => auth_type !== MCPAuthenticationType.NONE,
          then: (schema) =>
            schema
              .oneOf([
                MCPAuthenticationPerformer.ADMIN,
                MCPAuthenticationPerformer.PER_USER,
              ])
              .required(t("mcpAuthModal.authPerformer.required")),
          otherwise: (schema) => schema.notRequired(),
        }),
        api_token: Yup.string().when(["auth_type", "auth_performer"], {
          is: (auth_type: string, auth_performer: string) =>
            auth_type === MCPAuthenticationType.API_TOKEN &&
            auth_performer === MCPAuthenticationPerformer.ADMIN,
          then: (schema) => schema.required(t("mcpAuthModal.apiKey.required")),
          otherwise: (schema) => schema.notRequired(),
        }),
        oauth_client_id: Yup.string().when("auth_type", {
          is: MCPAuthenticationType.OAUTH,
          then: (schema) => schema.notRequired(),
          otherwise: (schema) => schema.notRequired(),
        }),
        oauth_client_secret: Yup.string().when("auth_type", {
          is: MCPAuthenticationType.OAUTH,
          then: (schema) => schema.notRequired(),
          otherwise: (schema) => schema.notRequired(),
        }),
        oauth_authorization_endpoint: Yup.string().when(
          ["auth_type", "oauth_provider_mode"],
          {
            is: (authType: string, providerMode: string) =>
              authType === MCPAuthenticationType.OAUTH &&
              providerMode === MCPOAuthProviderMode.KNOWN_PROVIDER,
            then: (schema) =>
              schema.required(t("mcpAuthModal.authorizationEndpoint.required")),
            otherwise: (schema) => schema.notRequired(),
          }
        ),
        oauth_token_endpoint: Yup.string().when(
          ["auth_type", "oauth_provider_mode"],
          {
            is: (authType: string, providerMode: string) =>
              authType === MCPAuthenticationType.OAUTH &&
              providerMode === MCPOAuthProviderMode.KNOWN_PROVIDER,
            then: (schema) =>
              schema.required(t("mcpAuthModal.tokenEndpoint.required")),
            otherwise: (schema) => schema.notRequired(),
          }
        ),
      }),
    [t]
  );

  const redirectUri = useMemo(() => {
    if (typeof window === "undefined") {
      return "https://{YOUR_DOMAIN}/mcp/oauth/callback";
    }
    return `${window.location.origin}/mcp/oauth/callback`;
  }, []);

  // Get the current frontend URL for redirect URI
  const { data: fullServer } = useSWR<MCPServer>(
    mcpServer ? SWR_KEYS.adminMcpServer(mcpServer.id) : null,
    errorHandlingFetcher
  );

  // Set the initial active tab based on the server configuration
  useEffect(() => {
    if (fullServer) {
      if (
        fullServer.auth_performer === MCPAuthenticationPerformer.ADMIN ||
        fullServer.auth_type === MCPAuthenticationType.NONE
      ) {
        setActiveAuthTab("admin");
      } else {
        setActiveAuthTab("per-user");
      }
      setAdvancedOpen(
        fullServer.oauth_provider_mode === MCPOAuthProviderMode.KNOWN_PROVIDER
      );
    }
  }, [fullServer]);

  const initialValues = useMemo<MCPAuthFormValues>(() => {
    if (!fullServer) {
      return {
        transport: mcpServer?.server_url
          ? getTransportFromUrl(mcpServer.server_url)
          : MCPTransportType.STREAMABLE_HTTP,
        auth_type: MCPAuthenticationType.OAUTH,
        auth_performer: MCPAuthenticationPerformer.PER_USER,
        api_token: "",
        auth_template: {
          headers: {},
          required_fields: [],
        },
        user_credentials: {},
        oauth_client_id: "",
        oauth_client_secret: "",
        oauth_provider_mode: MCPOAuthProviderMode.AUTO_DISCOVERY,
        oauth_authorization_endpoint: "",
        oauth_token_endpoint: "",
        oauth_scopes_override: "",
        oauth_additional_auth_params: "",
      };
    }

    // Only shared API-token servers return their header substitutions in
    // `admin_credentials`. For every other auth type that field carries OAuth
    // client credentials, which must not be replayed as per-user substitutions.
    const sharedApiToken =
      fullServer.auth_type === MCPAuthenticationType.API_TOKEN &&
      fullServer.auth_performer === MCPAuthenticationPerformer.ADMIN;

    return {
      transport: fullServer.server_url
        ? getTransportFromUrl(fullServer.server_url)
        : (fullServer.transport as MCPTransportType) ||
          MCPTransportType.STREAMABLE_HTTP,
      auth_type:
        (fullServer.auth_type as MCPAuthenticationType) ||
        MCPAuthenticationType.OAUTH,
      auth_performer:
        (fullServer.auth_performer as MCPAuthenticationPerformer) ||
        MCPAuthenticationPerformer.PER_USER,
      // Admin API Token
      api_token: fullServer.admin_credentials?.api_key || "",
      // OAuth Credentials
      oauth_client_id: fullServer.admin_credentials?.client_id || "",
      oauth_client_secret: fullServer.admin_credentials?.client_secret || "",
      oauth_provider_mode:
        fullServer.oauth_provider_mode || MCPOAuthProviderMode.AUTO_DISCOVERY,
      oauth_authorization_endpoint:
        fullServer.oauth_authorization_endpoint || "",
      oauth_token_endpoint: fullServer.oauth_token_endpoint || "",
      oauth_scopes_override: fullServer.oauth_scopes_override
        ? fullServer.oauth_scopes_override.join(", ")
        : "",
      oauth_additional_auth_params: fullServer.oauth_additional_auth_params
        ? JSON.stringify(fullServer.oauth_additional_auth_params)
        : "",
      // Auth Template
      auth_template: (fullServer.auth_template as MCPAuthTemplate) || {
        headers: {},
        required_fields: [],
      },
      // User Credentials (substitutions)
      user_credentials:
        (fullServer.user_credentials as Record<string, string>) ||
        (sharedApiToken
          ? (fullServer.admin_credentials as Record<string, string>)
          : undefined) ||
        {},
    };
  }, [fullServer, mcpServer?.server_url]);

  // Mirrors the LLM-provider `api_key_changed` pattern in
  // `web/src/sections/modals/languageModels/svc.ts`. The backend uses these flags
  // to decide whether to overwrite the stored OAuth credentials or to leave
  // them untouched, which prevents masked placeholders sent back from the
  // GET response from accidentally wiping out the real stored values.
  const computeOAuthChangedFlags = (values: MCPAuthFormValues) => {
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
  };

  // Per-key analogue of `computeOAuthChangedFlags` for the
  // `admin_credentials` dict (per-user API_TOKEN only).
  const computeAdminCredentialsChangedFlags = (
    values: MCPAuthFormValues
  ): Record<string, boolean> => {
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

  const computeAuthTemplateChangedFlags = (
    values: MCPAuthFormValues
  ): Record<string, boolean> => {
    const initialHeaders = initialValues.auth_template.headers;
    return Object.fromEntries(
      Object.entries(values.auth_template.headers).map(([name, value]) => [
        name,
        value !== initialHeaders[name],
      ])
    );
  };

  const constructServerData = (values: MCPAuthFormValues) => {
    if (!mcpServer) return null;
    const authType = values.auth_type;
    const oauthChangedFlags = computeOAuthChangedFlags(values);
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
        const parsed = JSON.parse(values.oauth_additional_auth_params);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          throw new Error(t("mcpAuthModal.errors.additionalParamsNotObject"));
        }
        parsedAdditionalAuthParams = Object.fromEntries(
          Object.entries(parsed).map(([key, value]) => [key, String(value)])
        );
      } catch (error) {
        throw new Error(
          error instanceof Error
            ? t("mcpAuthModal.errors.additionalParamsInvalidWithReason", {
                reason: error.message,
              })
            : t("mcpAuthModal.errors.additionalParamsInvalid")
        );
      }
    }

    return {
      name: mcpServer.name,
      description: mcpServer.description || undefined,
      server_url: mcpServer.server_url,
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
      existing_server_id: mcpServer.id,
    };
  };

  const handleSubmit = async (values: MCPAuthFormValues) => {
    if (!mcpServer) return;

    setIsSubmitting(true);

    try {
      // constructServerData throws on invalid oauth_additional_auth_params JSON;
      // keep it inside the try so the catch surfaces a toast.
      const serverData = constructServerData(values);
      if (!serverData) return;

      const authType = values.auth_type;
      // Step 1: Save the authentication configuration to the MCP server
      const { data: serverResult, error: serverError } =
        await upsertMCPServer(serverData);

      if (serverError || !serverResult) {
        throw new Error(
          serverError || t("mcpAuthModal.errors.saveConfigFailed")
        );
      }

      // Step 2: Update status to AWAITING_AUTH after successful config save
      if (authType === MCPAuthenticationType.OAUTH) {
        await updateMCPServerStatus(
          mcpServer.id,
          MCPServerStatus.AWAITING_AUTH
        );
      }

      // Step 3: For OAuth, initiate the OAuth flow
      if (authType === MCPAuthenticationType.OAUTH) {
        const oauthChangedFlags = computeOAuthChangedFlags(values);
        const oauthResponse = await fetch("/api/admin/mcp/oauth/connect", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            server_id: mcpServer.id.toString(),
            oauth_client_id: values.oauth_client_id,
            oauth_client_secret: values.oauth_client_secret,
            ...oauthChangedFlags,
            return_path: `${ADMIN_ROUTES.MCP_ACTIONS.path}/?server_id=${mcpServer.id}&trigger_fetch=true`,
            include_resource_param: true,
          }),
        });

        if (!oauthResponse.ok) {
          const error = await oauthResponse.json();
          // Refresh server list so latest status is visible after auth failure
          await mutateMcpServers();
          toggle(false);
          throw new Error(
            t("mcpAuthModal.errors.oauthInitFailed", { detail: error.detail })
          );
        }

        const oauthStart: MCPUserOAuthStartResponse =
          await oauthResponse.json();
        window.location.href = getMCPUserOAuthNavigationUrl(oauthStart);
      } else {
        // For non-OAuth authentication, trigger tools fetch in-place (no hard navigation)
        if (onTriggerFetchTools) {
          onTriggerFetchTools(mcpServer.id);
        } else {
          // Fallback to previous behavior if parent didn't provide handler
          window.location.href = `${ADMIN_ROUTES.MCP_ACTIONS.path}/?server_id=${mcpServer.id}&trigger_fetch=true`;
        }
        toggle(false);
      }
    } catch (error) {
      console.error("Error saving authentication:", error);
      // Ensure UI reflects latest status after any auth/config failure
      await mutateMcpServers();
      toast.error(
        error instanceof Error
          ? error.message
          : t("mcpAuthModal.errors.saveAuthFailed")
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal open={isOpen} onOpenChange={toggle}>
      <Modal.Content width="sm" height="lg" skipOverlay={skipOverlay}>
        <Modal.Header
          icon={SvgArrowExchange}
          title={
            mcpServer
              ? markdown(
                  t("mcpAuthModal.header.title", { name: mcpServer.name })
                )
              : t("mcpAuthModal.header.defaultTitle")
          }
          description={t("mcpAuthModal.header.description")}
        />

        <Formik<MCPAuthFormValues>
          initialValues={initialValues}
          validationSchema={validationSchema}
          onSubmit={handleSubmit}
          enableReinitialize
        >
          {({
            values,
            handleChange,
            setFieldValue,
            errors,
            touched,
            isValid,
            dirty,
          }) => {
            return (
              <Form className="flex flex-col h-full">
                <TransportAutoPopulate serverUrl={mcpServer?.server_url} />
                <Modal.Body>
                  <div className="flex flex-col gap-4 p-2">
                    {/* Authentication Type */}
                    <FormField
                      name="auth_type"
                      state={
                        errors.auth_type && touched.auth_type
                          ? "error"
                          : touched.auth_type
                            ? "success"
                            : "idle"
                      }
                    >
                      <FormField.Label>
                        {t("mcpAuthModal.authType.label")}
                      </FormField.Label>
                      <FormField.Control asChild>
                        <InputSelect
                          value={values.auth_type}
                          onValueChange={(value) => {
                            setFieldValue("auth_type", value);
                            if (value !== MCPAuthenticationType.OAUTH) {
                              setFieldValue(
                                "oauth_provider_mode",
                                MCPOAuthProviderMode.AUTO_DISCOVERY
                              );
                            }
                            // For OAuth + OAuth pass-through, we only support per-user auth
                            if (
                              value === MCPAuthenticationType.OAUTH ||
                              value === MCPAuthenticationType.PT_OAUTH
                            ) {
                              setFieldValue(
                                "auth_performer",
                                MCPAuthenticationPerformer.PER_USER
                              );
                            } else if (
                              value === MCPAuthenticationType.API_TOKEN
                            ) {
                              // Keep auth_performer in sync with the selected API token tab
                              setFieldValue(
                                "auth_performer",
                                activeAuthTab === "admin"
                                  ? MCPAuthenticationPerformer.ADMIN
                                  : MCPAuthenticationPerformer.PER_USER
                              );
                            }
                          }}
                        >
                          <InputSelect.Trigger
                            placeholder={t("mcpAuthModal.authType.placeholder")}
                            data-testid="mcp-auth-method-select"
                          />
                          <InputSelect.Content>
                            <InputSelect.Item
                              value={MCPAuthenticationType.OAUTH}
                              description={t(
                                "mcpAuthModal.authType.oauth.description"
                              )}
                            >
                              {t("mcpAuthModal.authType.oauth.label")}
                            </InputSelect.Item>
                            {isOAuthEnabled && (
                              <InputSelect.Item
                                value={MCPAuthenticationType.PT_OAUTH}
                                description={t(
                                  "mcpAuthModal.authType.ptOauth.description"
                                )}
                              >
                                {t("mcpAuthModal.authType.ptOauth.label")}
                              </InputSelect.Item>
                            )}
                            <InputSelect.Item
                              value={MCPAuthenticationType.API_TOKEN}
                              description={t(
                                "mcpAuthModal.authType.apiToken.description"
                              )}
                            >
                              {t("mcpAuthModal.authType.apiToken.label")}
                            </InputSelect.Item>
                            <InputSelect.Item
                              value={MCPAuthenticationType.NONE}
                              description={t(
                                "mcpAuthModal.authType.none.description"
                              )}
                            >
                              {t("mcpAuthModal.authType.none.label")}
                            </InputSelect.Item>
                          </InputSelect.Content>
                        </InputSelect>
                      </FormField.Control>
                      <FormField.Message
                        messages={{
                          error: errors.auth_type,
                        }}
                      />
                    </FormField>
                    <Divider paddingPerpendicular={0} />
                  </div>

                  {/* OAuth Section */}
                  {values.auth_type === MCPAuthenticationType.OAUTH && (
                    <div className="flex flex-col gap-4 px-2 py-2 bg-background-tint-00 rounded-12">
                      {/* OAuth Client ID */}
                      <FormField
                        name="oauth_client_id"
                        state={
                          errors.oauth_client_id && touched.oauth_client_id
                            ? "error"
                            : touched.oauth_client_id
                              ? "success"
                              : "idle"
                        }
                      >
                        <FormField.Label optional>
                          {t("mcpAuthModal.clientId.label")}
                        </FormField.Label>
                        <FormField.Control asChild>
                          <InputTypeIn
                            name="oauth_client_id"
                            value={values.oauth_client_id}
                            onChange={handleChange}
                            placeholder=" "
                          />
                        </FormField.Control>
                        <FormField.Message
                          messages={{
                            error: errors.oauth_client_id,
                          }}
                        />
                      </FormField>
                      {/* OAuth Client Secret */}
                      <FormField
                        name="oauth_client_secret"
                        state={
                          errors.oauth_client_secret &&
                          touched.oauth_client_secret
                            ? "error"
                            : touched.oauth_client_secret
                              ? "success"
                              : "idle"
                        }
                      >
                        <FormField.Label optional>
                          {t("mcpAuthModal.clientSecret.label")}
                        </FormField.Label>
                        <FormField.Control asChild>
                          <PasswordInputTypeIn
                            name="oauth_client_secret"
                            value={values.oauth_client_secret}
                            onChange={handleChange}
                            placeholder=" "
                          />
                        </FormField.Control>
                        <FormField.Message
                          messages={{
                            error: errors.oauth_client_secret,
                          }}
                        />
                      </FormField>

                      {/* Info Text */}
                      <div className="flex flex-col gap-2">
                        <Text as="p" font="secondary-body" color="text-03">
                          {t("mcpAuthModal.oauthInfo.discovery")}
                        </Text>
                        <Text as="p" font="secondary-body" color="text-03">
                          {t("mcpAuthModal.oauthInfo.manualRegistration")}
                        </Text>
                        {/* Redirect URI */}
                        <div className="flex items-center gap-1 w-full">
                          <Text
                            as="p"
                            font="secondary-body"
                            color="text-03"
                            nowrap
                          >
                            {markdown(t("mcpAuthModal.redirectUri.label"))}
                          </Text>
                          <Text
                            as="p"
                            font="secondary-mono"
                            color="text-04"
                            maxLines={1}
                          >
                            {redirectUri}
                          </Text>
                          <CopyButton
                            getCopyText={() => redirectUri}
                            tooltip={t("mcpAuthModal.redirectUri.copyTooltip")}
                            prominence="tertiary"
                            size="sm"
                          />
                        </div>
                      </div>

                      <SimpleCollapsible
                        open={advancedOpen}
                        onOpenChange={setAdvancedOpen}
                      >
                        <SimpleCollapsible.Header
                          title={t("mcpAuthModal.advanced.title")}
                          description={t("mcpAuthModal.advanced.description")}
                        />
                        <SimpleCollapsible.Content>
                          <Section alignItems="stretch" height="auto">
                            <FormField
                              name="oauth_provider_mode"
                              state={
                                errors.oauth_provider_mode &&
                                touched.oauth_provider_mode
                                  ? "error"
                                  : touched.oauth_provider_mode
                                    ? "success"
                                    : "idle"
                              }
                            >
                              <FormField.Label>
                                {t("mcpAuthModal.providerMode.label")}
                              </FormField.Label>
                              <FormField.Control asChild>
                                <InputSelect
                                  value={values.oauth_provider_mode}
                                  onValueChange={(value) => {
                                    setFieldValue("oauth_provider_mode", value);
                                  }}
                                >
                                  <InputSelect.Trigger
                                    placeholder={t(
                                      "mcpAuthModal.providerMode.placeholder"
                                    )}
                                  />
                                  <InputSelect.Content>
                                    <InputSelect.Item
                                      value={
                                        MCPOAuthProviderMode.AUTO_DISCOVERY
                                      }
                                      description={t(
                                        "mcpAuthModal.providerMode.autoDiscovery.description"
                                      )}
                                    >
                                      {t(
                                        "mcpAuthModal.providerMode.autoDiscovery.label"
                                      )}
                                    </InputSelect.Item>
                                    <InputSelect.Item
                                      value={
                                        MCPOAuthProviderMode.KNOWN_PROVIDER
                                      }
                                      description={t(
                                        "mcpAuthModal.providerMode.knownProvider.description"
                                      )}
                                    >
                                      {t(
                                        "mcpAuthModal.providerMode.knownProvider.label"
                                      )}
                                    </InputSelect.Item>
                                  </InputSelect.Content>
                                </InputSelect>
                              </FormField.Control>
                            </FormField>

                            {values.oauth_provider_mode ===
                              MCPOAuthProviderMode.KNOWN_PROVIDER && (
                              <>
                                <FormField
                                  name="oauth_authorization_endpoint"
                                  state={
                                    errors.oauth_authorization_endpoint &&
                                    touched.oauth_authorization_endpoint
                                      ? "error"
                                      : touched.oauth_authorization_endpoint
                                        ? "success"
                                        : "idle"
                                  }
                                >
                                  <FormField.Label>
                                    {t(
                                      "mcpAuthModal.authorizationEndpoint.label"
                                    )}
                                  </FormField.Label>
                                  <FormField.Control asChild>
                                    <InputTypeIn
                                      name="oauth_authorization_endpoint"
                                      value={
                                        values.oauth_authorization_endpoint
                                      }
                                      onChange={handleChange}
                                      placeholder={
                                        GOOGLE_AUTHORIZATION_ENDPOINT_HINT
                                      }
                                    />
                                  </FormField.Control>
                                  <FormField.Message
                                    messages={{
                                      error:
                                        errors.oauth_authorization_endpoint,
                                    }}
                                  />
                                </FormField>

                                <FormField
                                  name="oauth_token_endpoint"
                                  state={
                                    errors.oauth_token_endpoint &&
                                    touched.oauth_token_endpoint
                                      ? "error"
                                      : touched.oauth_token_endpoint
                                        ? "success"
                                        : "idle"
                                  }
                                >
                                  <FormField.Label>
                                    {t("mcpAuthModal.tokenEndpoint.label")}
                                  </FormField.Label>
                                  <FormField.Control asChild>
                                    <InputTypeIn
                                      name="oauth_token_endpoint"
                                      value={values.oauth_token_endpoint}
                                      onChange={handleChange}
                                      placeholder={GOOGLE_TOKEN_ENDPOINT_HINT}
                                    />
                                  </FormField.Control>
                                  <FormField.Message
                                    messages={{
                                      error: errors.oauth_token_endpoint,
                                    }}
                                  />
                                </FormField>

                                <FormField name="oauth_scopes_override">
                                  <FormField.Label optional>
                                    {t("mcpAuthModal.scopesOverride.label")}
                                  </FormField.Label>
                                  <FormField.Control asChild>
                                    <InputTypeIn
                                      name="oauth_scopes_override"
                                      value={values.oauth_scopes_override}
                                      onChange={handleChange}
                                      placeholder="https://www.googleapis.com/auth/logging.read"
                                    />
                                  </FormField.Control>
                                </FormField>

                                <FormField name="oauth_additional_auth_params">
                                  <FormField.Label optional>
                                    {t(
                                      "mcpAuthModal.additionalAuthParams.label"
                                    )}
                                  </FormField.Label>
                                  <FormField.Control asChild>
                                    <InputTypeIn
                                      name="oauth_additional_auth_params"
                                      value={
                                        values.oauth_additional_auth_params
                                      }
                                      onChange={handleChange}
                                      placeholder='{"access_type":"offline","prompt":"consent"}'
                                    />
                                  </FormField.Control>
                                </FormField>

                                <Text
                                  as="p"
                                  font="secondary-body"
                                  color="text-03"
                                >
                                  {t("mcpAuthModal.knownProvider.hint", {
                                    authorizationEndpoint:
                                      GOOGLE_AUTHORIZATION_ENDPOINT_HINT,
                                    tokenEndpoint: GOOGLE_TOKEN_ENDPOINT_HINT,
                                  })}
                                </Text>
                              </>
                            )}
                          </Section>
                        </SimpleCollapsible.Content>
                      </SimpleCollapsible>
                    </div>
                  )}

                  {/* API Key Section with Tabs */}
                  {values.auth_type === MCPAuthenticationType.API_TOKEN && (
                    <div className="flex flex-col gap-4 px-2 py-2 bg-background-tint-00 rounded-12">
                      <Tabs
                        value={activeAuthTab}
                        onValueChange={(value) => {
                          setActiveAuthTab(value as "per-user" | "admin");
                          // Update auth_performer based on tab selection
                          setFieldValue(
                            "auth_performer",
                            value === "per-user"
                              ? MCPAuthenticationPerformer.PER_USER
                              : MCPAuthenticationPerformer.ADMIN
                          );
                        }}
                      >
                        <Tabs.List>
                          <Tabs.Trigger value="per-user">
                            {t("mcpAuthModal.apiKeyTabs.perUser.label")}
                          </Tabs.Trigger>
                          <Tabs.Trigger value="admin">
                            {t("mcpAuthModal.apiKeyTabs.admin.label")}
                          </Tabs.Trigger>
                        </Tabs.List>

                        {/* Per-user Tab Content */}
                        <Tabs.Content value="per-user">
                          <PerUserAuthConfig
                            values={values}
                            setFieldValue={setFieldValue}
                          />
                        </Tabs.Content>

                        {/* Admin Tab Content */}
                        <Tabs.Content value="admin">
                          <div className="flex flex-col gap-4">
                            <PerUserAuthConfig
                              values={values}
                              setFieldValue={setFieldValue}
                              mode="shared"
                            />
                            <FormField
                              name="api_token"
                              state={
                                errors.api_token && touched.api_token
                                  ? "error"
                                  : touched.api_token
                                    ? "success"
                                    : "idle"
                              }
                            >
                              <FormField.Label>
                                {t("mcpAuthModal.sharedApiKey.label")}
                              </FormField.Label>
                              <FormField.Control asChild>
                                <PasswordInputTypeIn
                                  name="api_token"
                                  value={values.api_token}
                                  onChange={handleChange}
                                  placeholder={t(
                                    "mcpAuthModal.sharedApiKey.placeholder"
                                  )}
                                />
                              </FormField.Control>
                              <FormField.Description>
                                {t("mcpAuthModal.sharedApiKey.description")}
                              </FormField.Description>
                              <FormField.Message
                                messages={{
                                  error: errors.api_token,
                                }}
                              />
                            </FormField>
                          </div>
                        </Tabs.Content>
                      </Tabs>
                    </div>
                  )}
                  {values.auth_type !== MCPAuthenticationType.API_TOKEN && (
                    <PerUserAuthConfig
                      values={values}
                      setFieldValue={setFieldValue}
                    />
                  )}
                  {values.auth_type === MCPAuthenticationType.NONE && (
                    <MessageCard
                      title={t("mcpAuthModal.noAuthNotice.title")}
                      description={t("mcpAuthModal.noAuthNotice.description")}
                    />
                  )}
                  {values.auth_type === MCPAuthenticationType.PT_OAUTH && (
                    <MessageCard
                      title={t("mcpAuthModal.passThroughNotice.title")}
                      description={t(
                        "mcpAuthModal.passThroughNotice.description"
                      )}
                    />
                  )}
                </Modal.Body>

                <Modal.Footer>
                  <Button
                    prominence="tertiary"
                    type="button"
                    onClick={() => toggle(false)}
                  >
                    {t("mcpAuthModal.cancelButton.label")}
                  </Button>
                  <Button
                    disabled={!isValid || isSubmitting}
                    type="submit"
                    data-testid="mcp-auth-connect-button"
                  >
                    {isSubmitting
                      ? t("mcpAuthModal.submitButton.pendingLabel")
                      : t("mcpAuthModal.submitButton.label")}
                  </Button>
                </Modal.Footer>
              </Form>
            );
          }}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
