"use client";

import React, { useState, useMemo, useEffect } from "react";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import Modal from "@/refresh-components/Modal";
import { FormField } from "@/refresh-components/form/FormField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import Button from "@/refresh-components/buttons/Button";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import Text from "@/refresh-components/texts/Text";
import SvgArrowExchange from "@/icons/arrow-exchange";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  MCPTransportType,
} from "@/lib/tools/interfaces";
import { Separator } from "@/components/ui/separator";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/refresh-components/tabs/tabs";
import { PerUserAuthConfig } from "./PerUserAuthConfig";
import { createMCPServer } from "@/lib/tools/edit";
import { MCPServerWithStatus } from "./types";
import { updateMCPServerStatus } from "@/lib/mcpService";

interface MCPAuthenticationModalProps {
  mcpServer: MCPServerWithStatus | null;
  skipOverlay?: boolean;
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
}: MCPAuthenticationModalProps) {
  const { isOpen, toggle } = useModal();
  const [activeAuthTab, setActiveAuthTab] = useState<"per-user" | "admin">(
    "per-user"
  );
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { data: fullServer } = useSWR<MCPServerWithStatus>(
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

  const initialValues = useMemo(() => {
    if (!fullServer) {
      return {
        transport: MCPTransportType.STREAMABLE_HTTP,
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
      transport:
        (fullServer.transport as MCPTransportType) ||
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
      auth_template: fullServer.auth_template || {
        headers: { Authorization: "Bearer {api_key}" },
        required_fields: ["api_key"],
      },
      // User Credentials (substitutions)
      user_credentials: fullServer.user_credentials || {},
    };
  }, [fullServer]);

  const handleSubmit = async (values: any) => {
    if (!mcpServer) return;
    setIsSubmitting(true);

    try {
      const authType = values.auth_type;

      // Step 1: Save the authentication configuration to the MCP server
      const serverData = {
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

      const { data: serverResult, error: serverError } =
        await createMCPServer(serverData);

      if (serverError || !serverResult) {
        throw new Error(serverError || "Failed to save server configuration");
      }

      // Step 2: Update status to AWAITING_AUTH after successful config save
      if (authType === MCPAuthenticationType.OAUTH) {
        await updateMCPServerStatus(mcpServer.id, "AWAITING_AUTH");
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
            return_path: `/admin/mcp-actions/?server_id=${mcpServer.id}&trigger_fetch=true`,
            include_resource_param: true,
          }),
        });

        if (!oauthResponse.ok) {
          const error = await oauthResponse.json();
          throw new Error("Failed to initiate OAuth: " + error.detail);
        }

        const { oauth_url } = await oauthResponse.json();
        window.location.href = oauth_url;
      } else {
        // For non-OAuth authentication, redirect to the page with server_id and trigger_fetch
        window.location.href = `/admin/mcp-actions/?server_id=${mcpServer.id}&trigger_fetch=true`;
        toggle(false);
      }
    } catch (error) {
      console.error("Error saving authentication:", error);
      throw error;
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal open={isOpen} onOpenChange={toggle}>
      <Modal.Content tall skipOverlay={skipOverlay}>
        <Modal.Header className="p-4">
          <Modal.CloseButton />
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-1">
              <div className="flex items-center justify-center p-0.5 w-7 h-7">
                <SvgArrowExchange className="w-6 h-6 stroke-text-04" />
              </div>
            </div>
            <div className="flex flex-col">
              <Modal.Title>
                Authenticate {mcpServer?.name || "MCP Server"}
              </Modal.Title>
              <Modal.Description>
                Authenticate your connection to start using the MCP server.
              </Modal.Description>
            </div>
          </div>
        </Modal.Header>

        <Formik
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
          }) => (
            <Form className="flex flex-col h-full">
              <Modal.Body className="flex-1 overflow-y-auto max-h-[580px] p-2 bg-background-tint-01 w-full">
                <div className="flex flex-col gap-4 p-2">
                  {/* Transport */}
                  <FormField
                    name="transport"
                    state={
                      errors.transport && touched.transport
                        ? "error"
                        : touched.transport
                          ? "success"
                          : "idle"
                    }
                  >
                    <FormField.Label>Transport</FormField.Label>
                    <FormField.Control asChild>
                      <InputSelect
                        value={values.transport}
                        onValueChange={(value) =>
                          setFieldValue("transport", value)
                        }
                        options={[
                          {
                            value: MCPTransportType.STREAMABLE_HTTP,
                            label: "Streamable HTTP",
                          },
                          {
                            value: MCPTransportType.SSE,
                            label: "Server-Sent Events (SSE)",
                          },
                        ]}
                      />
                    </FormField.Control>
                    <FormField.Description>
                      Used for client-server communication and authentication.
                    </FormField.Description>
                    <FormField.Message
                      messages={{
                        error: errors.transport,
                      }}
                    />
                  </FormField>

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
                          // For OAuth, we only support per-user auth
                          if (value === MCPAuthenticationType.OAUTH) {
                            setFieldValue(
                              "auth_performer",
                              MCPAuthenticationPerformer.PER_USER
                            );
                          }
                        }}
                        options={[
                          {
                            value: MCPAuthenticationType.OAUTH,
                            label: "OAuth 2.0",
                            description:
                              "Each user need to authenticate via OAuth with their own credentials.",
                          },
                          {
                            value: MCPAuthenticationType.API_TOKEN,
                            label: "API Key",
                            description:
                              "Use per-user individual API key or organization-wide shared API key.",
                          },
                          {
                            value: MCPAuthenticationType.NONE,
                            label: "None",
                            description: "Not Recommended",
                          },
                        ]}
                      />
                    </FormField.Control>
                    <FormField.Message
                      messages={{
                        error: errors.auth_type,
                      }}
                    />
                  </FormField>

                  {/* Divider - only show if we have authentication fields */}
                  {(values.auth_type === MCPAuthenticationType.API_TOKEN ||
                    values.auth_type === MCPAuthenticationType.OAUTH) && (
                    <Separator className="my-0 bg-border-01" />
                  )}
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
                      <FormField.Label optional>Client Secret</FormField.Label>
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
                      <Text text03 secondaryBody>
                        Client ID and secret are optional if the server
                        connection supports Dynamic Client Registration (DCR).
                      </Text>
                      <Text text03 secondaryBody>
                        If your server does not support DCR, you need register
                        your Onyx instance with the server provider to obtain
                        these credentials first. Make sure to grant Onyx
                        necessary scopes/permissions for your actions.
                      </Text>

                      {/* Redirect URI */}
                      <div className="flex items-center gap-1 w-full">
                        <Text
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
                          text04
                          className="font-mono text-[12px] leading-[16px] truncate"
                        >
                          https://cloud.onyx.app/mcp/oauth/callback
                        </Text>
                        <CopyIconButton
                          getCopyText={() =>
                            "https://cloud.onyx.app/mcp/oauth/callback"
                          }
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
                          errors={errors}
                          touched={touched}
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
                              key is appropriate to share with everyone in your
                              organization.
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
              </Modal.Body>

              <Modal.Footer className="p-4 gap-2 bg-background-tint-00">
                <Button
                  main
                  tertiary
                  type="button"
                  onClick={() => toggle(false)}
                >
                  Skip for Now
                </Button>
                <Button main secondary type="button">
                  Save Configs Only
                </Button>
                <Button
                  main
                  primary
                  type="submit"
                  disabled={!isValid || isSubmitting}
                >
                  {isSubmitting ? "Saving..." : "Save & Connect"}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
