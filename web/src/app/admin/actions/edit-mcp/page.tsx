"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { BackButton } from "@/components/BackButton";
import { AdminPageTitle } from "@/components/admin/Title";
import { ToolIcon } from "@/components/icons/icons";
import { FiLink, FiCheck } from "react-icons/fi";
import CardSection from "@/components/admin/CardSection";
import { TextFormField } from "@/components/Field";
import { Button } from "@/components/ui/button";

import { usePopup } from "@/components/admin/connectors/Popup";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import Text from "@/components/ui/text";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  MCPTransportType,
} from "@/lib/tools/interfaces";
import {
  PerUserAuthTemplateConfig,
  OAuthConfig,
} from "@/components/admin/actions/forms";
import {
  MCPFormValues,
  MCPAuthTemplate,
  MCPServerDetail,
} from "@/components/admin/actions/interfaces";
import { ToolList } from "@/components/admin/actions/ToolList";

const validationSchema = Yup.object().shape({
  name: Yup.string().required("Name is required"),
  description: Yup.string(),
  server_url: Yup.string()
    .url("Must be a valid URL")
    .required("Server URL is required"),
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
  api_token: Yup.string().when("auth_type", {
    is: MCPAuthenticationType.API_TOKEN,
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

export default function NewMCPToolPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { popup, setPopup } = usePopup();

  const [loading, setLoading] = useState(false);

  const [oauthConnected, setOauthConnected] = useState(false);
  const [checkingOAuthStatus, setCheckingOAuthStatus] = useState(false);
  const [initialValues, setInitialValues] = useState<MCPFormValues>({
    name: "",
    description: "",
    server_url: "",
    transport: MCPTransportType.STREAMABLE_HTTP,
    auth_type: MCPAuthenticationType.NONE,
    auth_performer: MCPAuthenticationPerformer.ADMIN,
    api_token: "",
    oauth_client_id: "",
    oauth_client_secret: "",
  });
  const fetchedServerRef = useRef<string | null>(null);

  // We no longer probe by listing tools; OAuth connection state
  // is inferred from presence of return data in sessionStorage.

  // Memoize the server ID to prevent unnecessary re-renders
  const serverId = useMemo(() => searchParams.get("server_id"), [searchParams]);

  // Check for OAuth callback return
  useEffect(() => {
    const oauthReturn = sessionStorage.getItem("mcp_oauth_return");
    if (oauthReturn) {
      try {
        const { serverId: returnServerId, formValues } =
          JSON.parse(oauthReturn);
        sessionStorage.removeItem("mcp_oauth_return");

        // Set the form values and mark OAuth as connected
        setInitialValues(formValues);
        setOauthConnected(true);

        // Update URL to include the server ID
        router.push(`/admin/actions/edit-mcp?server_id=${returnServerId}`);
      } catch (error) {
        console.error("Failed to restore OAuth state:", error);
      }
    }
  }, []);

  // Load existing server data if server_id is provided
  useEffect(() => {
    if (!serverId || fetchedServerRef.current === serverId) return;

    const fetchServerData = async () => {
      setLoading(true);
      fetchedServerRef.current = serverId; // Mark as fetching/fetched

      try {
        const response = await fetch(`/api/admin/mcp/servers/${serverId}`);
        if (!response.ok) {
          throw new Error(await response.text());
        }
        const server: MCPServerDetail = await response.json();

        // Build auth_template if this is a per-user server
        let auth_template: MCPAuthTemplate | undefined;
        if (
          server.auth_performer === MCPAuthenticationPerformer.PER_USER &&
          server.auth_template
        ) {
          auth_template = server.auth_template;
        }

        setInitialValues({
          name: server.name,
          description: server.description || "",
          server_url: server.server_url,
          transport: server.transport,
          auth_type: server.auth_type,
          auth_performer:
            server.auth_type === MCPAuthenticationType.OAUTH
              ? MCPAuthenticationPerformer.PER_USER
              : server.auth_performer || MCPAuthenticationPerformer.ADMIN,
          api_token: server.admin_credentials?.api_key || "",
          auth_template,
          user_credentials: server.user_credentials || {},
          oauth_client_id: server.admin_credentials?.client_id || "",
          oauth_client_secret: server.admin_credentials?.client_secret || "",
        });
      } catch (error) {
        console.error("Failed to load server data:", error);
        setPopup({
          message: "Failed to load server configuration",
          type: "error",
        });
        fetchedServerRef.current = null; // Reset on error so user can retry
      } finally {
        setLoading(false);
      }
    };

    fetchServerData();
  }, [serverId]); // Only depend on the memoized server ID

  const handleOAuthConnect = async (values: MCPFormValues) => {
    setCheckingOAuthStatus(true);
    try {
      // First, create the MCP server if it doesn't exist
      const createResponse = await fetch("/api/admin/mcp/servers/create", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          name: values.name,
          description: values.description,
          server_url: values.server_url,
          transport: values.transport,
          auth_type: values.auth_type,
          // OAuth currently only supports per-user auth
          auth_performer: MCPAuthenticationPerformer.PER_USER,
          oauth_client_id: values.oauth_client_id,
          oauth_client_secret: values.oauth_client_secret,
          existing_server_id: serverId ? parseInt(serverId) : undefined,
        }),
      });

      if (!createResponse.ok) {
        const error = await createResponse.json();
        throw new Error(error.detail || "Failed to create OAuth server");
      }

      const currServerId = (await createResponse.json()).server_id;
      // Update the URL immediately so subsequent interactions use the server id.
      router.replace(`/admin/actions/edit-mcp?server_id=${currServerId}`);

      // Initiate OAuth flow
      const oauthResponse = await fetch("/api/admin/mcp/oauth/connect", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          server_id: currServerId.toString(),
          oauth_client_id: values.oauth_client_id,
          oauth_client_secret: values.oauth_client_secret,
          return_path:
            "/admin/actions/edit-mcp?server_id=" + currServerId.toString(),
          include_resource_param: true,
        }),
      });

      if (!oauthResponse.ok) {
        const error = await oauthResponse.json();
        throw new Error("Failed to initiate OAuth: " + error.detail);
      }

      const { oauth_url } = await oauthResponse.json();

      // Store current form state to restore after OAuth callback
      sessionStorage.setItem(
        "mcp_oauth_return",
        JSON.stringify({
          serverId: currServerId,
          formValues: values,
        })
      );

      // Redirect to OAuth provider
      window.location.href = oauth_url;
    } catch (error) {
      console.error("OAuth connect error:", error);
      setPopup({
        message:
          error instanceof Error ? error.message : "Failed to connect OAuth",
        type: "error",
      });
    } finally {
      setCheckingOAuthStatus(false);
    }
  };

  const verbRoot = serverId ? "Updat" : "Creat";
  return (
    <div className="mx-auto container">
      {popup}
      <BackButton routerOverride="/admin/actions" />

      <AdminPageTitle
        title={verbRoot + "e MCP Server Actions"}
        icon={<ToolIcon size={32} className="my-auto" />}
      />

      <Text className="mb-4">
        Configure an MCP (Model Context Protocol) server to create actions that
        can interact with external systems.
      </Text>

      <CardSection>
        {loading ? (
          <div className="flex justify-center py-8">
            <div className="text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 mx-auto mb-2"></div>
              <Text>Loading server configuration...</Text>
            </div>
          </div>
        ) : (
          <Formik
            initialValues={initialValues}
            enableReinitialize={true}
            validationSchema={validationSchema}
            onSubmit={() => {}}
          >
            {({ values, setFieldValue, errors, touched }) => {
              return (
                <Form
                  style={{ width: 600, position: "relative" }}
                  className="isolate"
                >
                  <div className="space-y-6 relative">
                    <div>
                      <h3 className="text-lg font-medium mb-4">
                        Basic Information
                      </h3>
                      <div className="space-y-4">
                        <TextFormField
                          name="name"
                          label="Action Name"
                          placeholder="e.g., My MCP Tool"
                          width="min-w-96"
                        />
                        <TextFormField
                          name="description"
                          label="Description"
                          placeholder="Brief description of what this MCP server does"
                          width="min-w-96"
                        />
                        <TextFormField
                          name="server_url"
                          label="Server URL"
                          placeholder="https://your-mcp-server.com"
                          width="min-w-96"
                        />
                        <div>
                          <Label htmlFor="transport">Transport</Label>
                          <Select
                            value={values.transport}
                            onValueChange={(value) =>
                              setFieldValue("transport", value)
                            }
                          >
                            <SelectTrigger className="mt-1">
                              <SelectValue placeholder="Select transport" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem
                                value={MCPTransportType.STREAMABLE_HTTP}
                              >
                                Streamable HTTP
                              </SelectItem>
                              <SelectItem value={MCPTransportType.SSE}>
                                SSE
                              </SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                    </div>

                    <Separator />

                    <div>
                      <h3 className="text-lg font-medium mb-4">
                        Authentication Configuration
                      </h3>
                      <div className="space-y-4">
                        <div>
                          <Label htmlFor="auth_type">Authentication Type</Label>
                          <Select
                            value={values.auth_type}
                            onValueChange={(value) => {
                              setFieldValue("auth_type", value);
                              // For OAuth, we only support per-user auth. Force performer accordingly.
                              if (value === MCPAuthenticationType.OAUTH) {
                                setFieldValue(
                                  "auth_performer",
                                  MCPAuthenticationPerformer.PER_USER
                                );
                              }
                            }}
                          >
                            <SelectTrigger className="mt-1">
                              <SelectValue placeholder="Select authentication type" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value={MCPAuthenticationType.NONE}>
                                None
                              </SelectItem>
                              <SelectItem
                                value={MCPAuthenticationType.API_TOKEN}
                              >
                                API Token
                              </SelectItem>
                              <SelectItem value={MCPAuthenticationType.OAUTH}>
                                OAuth
                              </SelectItem>
                            </SelectContent>
                          </Select>
                          {errors.auth_type && touched.auth_type && (
                            <div className="text-red-500 text-sm mt-1">
                              {errors.auth_type}
                            </div>
                          )}
                        </div>

                        {values.auth_type !== MCPAuthenticationType.NONE &&
                          values.auth_type !== MCPAuthenticationType.OAUTH && (
                            <div>
                              <Label htmlFor="auth_performer">
                                Who performs authentication?
                              </Label>
                              <Select
                                value={values.auth_performer}
                                onValueChange={(value) =>
                                  setFieldValue("auth_performer", value)
                                }
                              >
                                <SelectTrigger className="mt-1">
                                  <SelectValue placeholder="Select authentication performer" />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem
                                    value={MCPAuthenticationPerformer.ADMIN}
                                  >
                                    Admin (shared credentials)
                                  </SelectItem>
                                  <SelectItem
                                    value={MCPAuthenticationPerformer.PER_USER}
                                  >
                                    Per-user (individual credentials)
                                  </SelectItem>
                                </SelectContent>
                              </Select>
                              {errors.auth_performer &&
                                touched.auth_performer && (
                                  <div className="text-red-500 text-sm mt-1">
                                    {errors.auth_performer}
                                  </div>
                                )}
                            </div>
                          )}

                        {values.auth_type === MCPAuthenticationType.API_TOKEN &&
                          values.auth_performer ===
                            MCPAuthenticationPerformer.ADMIN && (
                            <TextFormField
                              name="api_token"
                              label="API Token"
                              placeholder="Enter your API token"
                              type="password"
                              width="min-w-96"
                            />
                          )}

                        {values.auth_type === MCPAuthenticationType.API_TOKEN &&
                          values.auth_performer ===
                            MCPAuthenticationPerformer.PER_USER && (
                            <PerUserAuthTemplateConfig
                              values={values}
                              setFieldValue={setFieldValue}
                              errors={errors}
                              touched={touched}
                            />
                          )}

                        {values.auth_type === MCPAuthenticationType.OAUTH && (
                          <OAuthConfig
                            values={values}
                            setFieldValue={setFieldValue}
                            errors={errors}
                            touched={touched}
                          />
                        )}
                      </div>
                    </div>

                    {values.auth_type === MCPAuthenticationType.OAUTH && (
                      <div className="flex items-center gap-2">
                        <Button
                          type="button"
                          onClick={() => handleOAuthConnect(values)}
                          disabled={
                            checkingOAuthStatus ||
                            !values.name.trim() ||
                            !values.server_url.trim()
                          }
                          className="flex-1"
                        >
                          {checkingOAuthStatus ? (
                            "Connecting..."
                          ) : oauthConnected ? (
                            <>
                              <FiCheck className="mr-2 h-4 w-4" />
                              OAuth Connected
                            </>
                          ) : (
                            <>
                              <FiLink className="mr-2 h-4 w-4" />
                              Connect OAuth
                            </>
                          )}
                        </Button>
                      </div>
                    )}
                    <Separator />
                    <ToolList
                      values={values}
                      verbRoot={verbRoot}
                      serverId={serverId ? parseInt(serverId) : undefined}
                      oauthConnected={oauthConnected}
                      setPopup={setPopup}
                    />
                  </div>
                </Form>
              );
            }}
          </Formik>
        )}
      </CardSection>
    </div>
  );
}
