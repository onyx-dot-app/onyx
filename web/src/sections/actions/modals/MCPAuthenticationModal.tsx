"use client";

import { useState, useMemo, useEffect } from "react";
import useSWR, { KeyedMutator } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import Modal from "@/refresh-components/Modal";
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
  Tabs,
} from "@opal/components";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import { markdown } from "@opal/utils";
import Text from "@/refresh-components/texts/Text";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  MCPOAuthProviderMode,
  MCPTransportType,
  MCPServerStatus,
  MCPServer,
  MCPServersResponse,
} from "@/lib/tools/interfaces";
import { PerUserAuthConfig } from "@/sections/actions/PerUserAuthConfig";
import { updateMCPServerStatus, upsertMCPServer } from "@/lib/tools/mcpService";
import { toast } from "@/hooks/useToast";
import { SvgArrowExchange } from "@opal/icons";
import { useAuthType } from "@/lib/hooks";
import { AuthType } from "@/lib/constants";

interface MCPAuthenticationModalProps {
  mcpServer: MCPServer | null;
  skipOverlay?: boolean;
  onTriggerFetchTools?: (serverId: number) => Promise<void> | void;
  mutateMcpServers: KeyedMutator<MCPServersResponse>;
}

interface MCPAuthTemplate {
  headers: Record<string, string>;
  required_fields: string[];
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

const validationSchema = Yup.object().shape({
  transport: Yup.string()
    .oneOf([MCPTransportType.STREAMABLE_HTTP, MCPTransportType.SSE])
    .required("Transport is required"),
  auth_type: Yup.string()
    .oneOf([
      MCPAuthenticationType.NONE,
      MCPAuthenticationType.API_TOKEN,
      MCPAuthenticationType.OAUTH,
      MCPAuthenticationType.PT_OAUTH,
    ])
    .required("Authentication type is required"),
  auth_performer: Yup.string().when("auth_type", {
    is: (auth_type: string) => auth_type !== MCPAuthenticationType.NONE,
    then: (schema) =>
      schema
        .oneOf([
          MCPAuthenticationPerformer.ADMIN,
          MCPAuthenticationPerformer.PER_USER,
        ])
        .required("Authentication performer is required"),
    otherwise: (schema) => schema.notRequired(),
  }),
  api_token: Yup.string().when(["auth_type", "auth_performer"], {
    is: (auth_type: string, auth_performer: string) =>
      auth_type === MCPAuthenticationType.API_TOKEN &&
      auth_performer === MCPAuthenticationPerformer.ADMIN,
    then: (schema) => schema.required("API token is required"),
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
        schema.required(
          "Authorization endpoint is required in known-provider mode"
        ),
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
        schema.required("Token endpoint is required in known-provider mode"),
      otherwise: (schema) => schema.notRequired(),
    }
  ),
});

export default function MCPAuthenticationModal({
  mcpServer,
  skipOverlay = false,
  onTriggerFetchTools,
  mutateMcpServers,
}: MCPAuthenticationModalProps) {
  const { isOpen, toggle } = useModal();
  const [activeAuthTab, setActiveAuthTab] = useState<"per-user" | "admin">(
    "per-user"
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Open the Advanced (known-provider) section by default when configured.
  const [advancedOpen, setAdvancedOpen] = useState(false);

  // Check if OAuth is enabled for the Onyx instance
  const authType = useAuthType();
  const isOAuthEnabled =
    authType === AuthType.OIDC || authType === AuthType.GOOGLE_OAUTH;

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

  // Helper function to determine transport from URL
  const getTransportFromUrl = (url: string): MCPTransportType => {
    const lowerUrl = url.toLowerCase();
    if (lowerUrl.endsWith("sse")) {
      return MCPTransportType.SSE;
    } else if (lowerUrl.endsWith("mcp")) {
      return MCPTransportType.STREAMABLE_HTTP;
    }
    // Default to STREAMABLE_HTTP
    return MCPTransportType.STREAMABLE_HTTP;
  };

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
          headers: { Authorization: "Bearer {api_key}" },
          required_fields: ["api_key"],
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
        headers: { Authorization: "Bearer {api_key}" },
        required_fields: ["api_key"],
      },
      // User Credentials (substitutions)
      user_credentials:
        (fullServer.user_credentials as Record<string, string>) || {},
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
    if (
      values.auth_type !== MCPAuthenticationType.API_TOKEN ||
      values.auth_performer !== MCPAuthenticationPerformer.PER_USER
    ) {
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

  const constructServerData = (values: MCPAuthFormValues) => {
    if (!mcpServer) return null;
    const authType = values.auth_type;
    const oauthChangedFlags = computeOAuthChangedFlags(values);
    const isPerUserApiToken =
      values.auth_performer === MCPAuthenticationPerformer.PER_USER &&
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
          throw new Error("Additional auth params must be a JSON object");
        }
        parsedAdditionalAuthParams = Object.fromEntries(
          Object.entries(parsed).map(([key, value]) => [key, String(value)])
        );
      } catch (error) {
        throw new Error(
          error instanceof Error
            ? `Invalid additional auth params JSON: ${error.message}`
            : "Invalid additional auth params JSON"
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
      api_token:
        authType === MCPAuthenticationType.API_TOKEN &&
        values.auth_performer === MCPAuthenticationPerformer.ADMIN
          ? values.api_token
          : undefined,
      auth_template: isPerUserApiToken ? values.auth_template : undefined,
      admin_credentials: isPerUserApiToken
        ? values.user_credentials || {}
        : undefined,
      admin_credentials_changed: isPerUserApiToken
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
        throw new Error(serverError || "Failed to save server configuration");
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
            return_path: `/admin/actions/mcp/?server_id=${mcpServer.id}&trigger_fetch=true`,
            include_resource_param: true,
          }),
        });

        if (!oauthResponse.ok) {
          const error = await oauthResponse.json();
          // Refresh server list so latest status is visible after auth failure
          await mutateMcpServers();
          toggle(false);
          throw new Error("Failed to initiate OAuth: " + error.detail);
        }

        const { oauth_url } = await oauthResponse.json();
        window.location.href = oauth_url;
      } else {
        // For non-OAuth authentication, trigger tools fetch in-place (no hard navigation)
        if (onTriggerFetchTools) {
          onTriggerFetchTools(mcpServer.id);
        } else {
          // Fallback to previous behavior if parent didn't provide handler
          window.location.href = `/admin/actions/mcp/?server_id=${mcpServer.id}&trigger_fetch=true`;
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
          : "Failed to save authentication configuration"
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
              ? markdown(`Authenticate *${mcpServer.name}*`)
              : "Authenticate MCP Server"
          }
          description="Authenticate your connection to start using the MCP server."
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
            // Auto-populate transport based on URL
            useEffect(() => {
              if (mcpServer?.server_url) {
                const transport = getTransportFromUrl(mcpServer.server_url);
                setFieldValue("transport", transport);
              }
            }, [mcpServer?.server_url, setFieldValue]);

            return (
              <Form className="flex flex-col h-full">
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
                      <FormField.Label>Authentication Method</FormField.Label>
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
                            placeholder="Select method"
                            data-testid="mcp-auth-method-select"
                          />
                          <InputSelect.Content>
                            <InputSelect.Item
                              value={MCPAuthenticationType.OAUTH}
                              description="Each user need to authenticate via OAuth with their own credentials."
                            >
                              OAuth
                            </InputSelect.Item>
                            {isOAuthEnabled && (
                              <InputSelect.Item
                                value={MCPAuthenticationType.PT_OAUTH}
                                description="Forward the user's OAuth access token used to authenticate Onyx."
                              >
                                OAuth Pass-through
                              </InputSelect.Item>
                            )}
                            <InputSelect.Item
                              value={MCPAuthenticationType.API_TOKEN}
                              description="Use per-user individual API key or organization-wide shared API key."
                            >
                              API Key
                            </InputSelect.Item>
                            <InputSelect.Item
                              value={MCPAuthenticationType.NONE}
                              description="Not Recommended"
                            >
                              None
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
                    <Divider paddingPerpendicular="fit" />
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
                        <FormField.Label optional>Client ID</FormField.Label>
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
                          Client Secret
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
                        <Text as="p" text03 secondaryBody>
                          Client ID and secret are optional if the server
                          connection supports Dynamic Client Registration (DCR).
                        </Text>
                        <Text as="p" text03 secondaryBody>
                          If your server does not support DCR, you need register
                          your Onyx instance with the server provider to obtain
                          these credentials first. Make sure to grant Onyx
                          necessary scopes/permissions for your actions.
                        </Text>
                        {/* Redirect URI */}
                        <div className="flex items-center gap-1 w-full">
                          <Text
                            as="p"
                            text03
                            secondaryBody
                            className="whitespace-nowrap"
                          >
                            Use{" "}
                            <span className="font-secondary-action">
                              redirect URI
                            </span>
                            :
                          </Text>
                          <Text
                            as="p"
                            text04
                            className="font-mono text-[12px] leading-[16px] truncate"
                          >
                            {redirectUri}
                          </Text>
                          <CopyButton
                            getCopyText={() => redirectUri}
                            tooltip="Copy redirect URI"
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
                          title="Advanced"
                          description="Configure a known OAuth provider with explicit authorization and token endpoints instead of automatic discovery."
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
                              <FormField.Label>Provider Mode</FormField.Label>
                              <FormField.Control asChild>
                                <InputSelect
                                  value={values.oauth_provider_mode}
                                  onValueChange={(value) => {
                                    setFieldValue("oauth_provider_mode", value);
                                  }}
                                >
                                  <InputSelect.Trigger placeholder="Select mode" />
                                  <InputSelect.Content>
                                    <InputSelect.Item
                                      value={
                                        MCPOAuthProviderMode.AUTO_DISCOVERY
                                      }
                                      description="Use MCP SDK challenge/discovery flow (default)."
                                    >
                                      Auto Discovery
                                    </InputSelect.Item>
                                    <InputSelect.Item
                                      value={
                                        MCPOAuthProviderMode.KNOWN_PROVIDER
                                      }
                                      description="Use configured authorization/token endpoints."
                                    >
                                      Known Provider
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
                                    Authorization Endpoint
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
                                    Token Endpoint
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
                                    Scopes Override (comma-separated)
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
                                    Additional Auth Params (JSON)
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

                                <Text as="p" text03 secondaryBody>
                                  Known-provider mode requires endpoint
                                  configuration. Google reference endpoints:
                                  authorization{" "}
                                  {GOOGLE_AUTHORIZATION_ENDPOINT_HINT} and token{" "}
                                  {GOOGLE_TOKEN_ENDPOINT_HINT}.
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
                            Individual Key (Per User)
                          </Tabs.Trigger>
                          <Tabs.Trigger value="admin">
                            Shared Key (Admin)
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
                          <div className="flex flex-col gap-4 px-2 py-2 bg-background-tint-00 rounded-12">
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
                              <FormField.Label>API Key</FormField.Label>
                              <FormField.Control asChild>
                                <PasswordInputTypeIn
                                  name="api_token"
                                  value={values.api_token}
                                  onChange={handleChange}
                                  placeholder="Shared API key for your organization"
                                />
                              </FormField.Control>
                              <FormField.Description>
                                Do not use your personal API key. Make sure this
                                key is appropriate to share with everyone in
                                your organization.
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
                  {values.auth_type === MCPAuthenticationType.NONE && (
                    <MessageCard
                      title="No authentication for this MCP server"
                      description="No authentication will be used for this connection. Make sure you trust this server. You are responsible for actions taken with this connection."
                    />
                  )}
                  {values.auth_type === MCPAuthenticationType.PT_OAUTH && (
                    <MessageCard
                      title="Use pass-through for services with shared identity provider."
                      description="Onyx will forward the user's OAuth access token directly to the server as an Authorization header. Make sure the server supports authentication with the same provider."
                    />
                  )}
                </Modal.Body>

                <Modal.Footer>
                  <Button
                    prominence="tertiary"
                    type="button"
                    onClick={() => toggle(false)}
                  >
                    Cancel
                  </Button>
                  <Button
                    disabled={!isValid || isSubmitting}
                    type="submit"
                    data-testid="mcp-auth-connect-button"
                  >
                    {isSubmitting ? "Connecting..." : "Connect"}
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
