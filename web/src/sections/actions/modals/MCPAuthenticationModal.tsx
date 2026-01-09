"use client";

import React, { useState, useMemo, useEffect } from "react";
import useSWR, { KeyedMutator } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import Modal from "@/refresh-components/Modal";
import { FormField } from "@/refresh-components/form/FormField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import Button from "@/refresh-components/buttons/Button";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import Text from "@/refresh-components/texts/Text";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  MCPTransportType,
  MCPServerStatus,
  MCPServer,
  MCPServersResponse,
} from "@/lib/tools/interfaces";
import Separator from "@/refresh-components/Separator";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/refresh-components/tabs/tabs";
import { PerUserAuthConfig } from "@/sections/actions/PerUserAuthConfig";
import { updateMCPServerStatus, upsertMCPServer } from "@/lib/tools/mcpService";
import Message from "@/refresh-components/messages/Message";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { SvgArrowExchange } from "@opal/icons";
import { useAuthType } from "@/lib/hooks";
import { AuthType } from "@/lib/constants";

interface MCPAuthenticationModalProps {
  mcpServer: MCPServer | null;
  skipOverlay?: boolean;
  setPopup?: (spec: PopupSpec) => void;
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
}

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
});

export default function MCPAuthenticationModal({
  mcpServer,
  skipOverlay = false,
  setPopup,
  onTriggerFetchTools,
  mutateMcpServers,
}: MCPAuthenticationModalProps) {
  const { isOpen, toggle } = useModal();
  const [activeAuthTab, setActiveAuthTab] = useState<"per-user" | "admin">(
    "per-user"
  );
  const [isSubmitting, setIsSubmitting] = useState(false);

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
    mcpServer ? `/api/admin/mcp/servers/${mcpServer.id}` : null,
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

  const constructServerData = (values: MCPAuthFormValues) => {
    if (!mcpServer) return null;
    const authType = values.auth_type;

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
      auth_template:
        values.auth_performer === MCPAuthenticationPerformer.PER_USER &&
        authType === MCPAuthenticationType.API_TOKEN
          ? values.auth_template
          : undefined,
      admin_credentials:
        values.auth_performer === MCPAuthenticationPerformer.PER_USER &&
        authType === MCPAuthenticationType.API_TOKEN
          ? values.user_credentials || {}
          : undefined,
      oauth_client_id:
        authType === MCPAuthenticationType.OAUTH
          ? values.oauth_client_id
          : undefined,
      oauth_client_secret:
        authType === MCPAuthenticationType.OAUTH
          ? values.oauth_client_secret
          : undefined,
      existing_server_id: mcpServer.id,
    };
  };

  const handleSubmit = async (values: MCPAuthFormValues) => {
    const serverData = constructServerData(values);
    if (!serverData || !mcpServer) return;

    setIsSubmitting(true);

    try {
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
        const oauthResponse = await fetch("/api/admin/mcp/oauth/connect", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            server_id: mcpServer.id.toString(),
            oauth_client_id: values.oauth_client_id,
            oauth_client_secret: values.oauth_client_secret,
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
      setPopup?.({
        message:
          error instanceof Error
            ? error.message
            : "Failed to save authentication configuration",
        type: "error",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal open={isOpen} onOpenChange={toggle}>
      <Modal.Content tall skipOverlay={skipOverlay}>
        <Modal.Header
          icon={SvgArrowExchange}
          title={`Authenticate ${mcpServer?.name || "MCP Server"}`}
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
                    <Separator className="py-0" />
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
                            showClearButton={false}
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
                            showClearButton={false}
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
                          <CopyIconButton
                            getCopyText={() => redirectUri}
                            tooltip="Copy redirect URI"
                            internal
                          />
                        </div>
                      </div>
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
                        className="w-full"
                      >
                        <TabsList className="w-full">
                          <TabsTrigger value="per-user" className="flex-1">
                            Individual Key (Per User)
                          </TabsTrigger>
                          <TabsTrigger value="admin" className="flex-1">
                            Shared Key (Admin)
                          </TabsTrigger>
                        </TabsList>

                        {/* Per-user Tab Content */}
                        <TabsContent value="per-user" className="w-full">
                          <PerUserAuthConfig
                            values={values}
                            setFieldValue={setFieldValue}
                          />
                        </TabsContent>

                        {/* Admin Tab Content */}
                        <TabsContent value="admin" className="w-full">
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
                                  showClearButton={false}
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
                        </TabsContent>
                      </Tabs>
                    </div>
                  )}
                  {values.auth_type === MCPAuthenticationType.NONE && (
                    <Message
                      text="No authentication for this MCP server"
                      description="No authentication will be used for this connection. Make sure you trust this server. You are responsible for actions taken with this connection."
                      default
                      medium
                      static
                      className="w-full"
                      close={false}
                    />
                  )}
                  {values.auth_type === MCPAuthenticationType.PT_OAUTH && (
                    <Message
                      text="Use pass-through for services with shared identity provider."
                      description="Onyx will forward the user's OAuth access token directly to the server as an Authorization header. Make sure the server supports authentication with the same provider."
                      default
                      medium
                      static
                      className="w-full"
                      close={false}
                    />
                  )}
                </Modal.Body>

                <Modal.Footer>
                  <Button
                    main
                    tertiary
                    type="button"
                    onClick={() => toggle(false)}
                  >
                    Cancel
                  </Button>
                  <Button
                    main
                    primary
                    type="submit"
                    disabled={!isValid || isSubmitting}
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
