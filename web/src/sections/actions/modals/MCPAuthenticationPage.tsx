"use client";

import { useId, useState, useMemo, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import type { MCPAuthFormValues } from "@/sections/actions/modals/types";
import {
  getMCPAuthInitialValues,
  getAuthTemplateForMethod,
  buildMCPAuthPayload,
  validateMCPAuthCredentials,
} from "@/sections/actions/modals/mcpAuthForm";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { SvgArrowLeft } from "@opal/icons";
import { Section } from "@opal/layouts";
import { Button, MessageCard, Tabs } from "@opal/components";
import { Formik, Form, type FormikHelpers } from "formik";
import * as Yup from "yup";
import { useSettings } from "@/lib/settings/hooks";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  MCPOAuthProviderMode,
  MCPTransportType,
  MCPServerStatus,
  MCPServer,
} from "@/lib/mcp/types";
import { PerUserAuthConfig } from "@/sections/actions/PerUserAuthConfig";
import {
  discoverMCPOAuth,
  MCPOAuthError,
  type MCPOAuthFailureReason,
  getMCPUserOAuthNavigationUrl,
  updateMCPServerStatus,
  startMCPAdminOAuth,
  upsertMCPServer,
} from "@/lib/mcp/svc";
import { Content } from "@opal/layouts";
import { MCPOAuthFields } from "@/sections/actions/modals/MCPOAuthFields";
import { MCPApiTokenFields } from "@/sections/actions/modals/MCPApiTokenFields";
import { MCPAdvancedFields } from "@/sections/actions/modals/MCPAdvancedFields";
import { useOAuthPassThroughEnabled } from "@/lib/auth/hooks";

import MCPFormActions from "@/sections/actions/modals/MCPFormActions";
import MCPFormDirtyObserver from "@/sections/actions/modals/MCPFormDirtyObserver";

interface MCPAuthenticationPageProps {
  active: boolean;
  variant?: "modal" | "page";
  readOnly?: boolean;
  footerTarget?: HTMLDivElement | null;
  mcpServer: MCPServer;
  onTriggerFetchTools?: (serverId: number) => Promise<void> | void;
  onBusyChange: (busy: boolean) => void;
  onDirtyChange: (dirty: boolean) => void;
  onCancel?: () => void;
  onSaved: () => Promise<void>;
  onBack?: () => void;
  onComplete: () => Promise<void> | void;
}

export default function MCPAuthenticationPage({
  active,
  variant = "modal",
  readOnly = false,
  footerTarget = null,
  mcpServer,
  onTriggerFetchTools,
  onBusyChange,
  onDirtyChange,
  onCancel,
  onSaved,
  onBack,
  onComplete,
}: MCPAuthenticationPageProps) {
  const formId = useId();
  const t = useTranslations("actions");
  const { appName } = useSettings();
  const [initialValues] = useState(() => getMCPAuthInitialValues(mcpServer));
  const persistedValues = useRef(initialValues);
  const [isSubmitting, setIsSubmitting] = useState(false);
  useEffect(() => onBusyChange(isSubmitting), [isSubmitting, onBusyChange]);
  const [connectionSettingsOpen, setConnectionSettingsOpen] = useState(false);
  const [connectionError, setConnectionError] = useState<{
    stage: "saveStage" | "oauthStage" | "discoveryStage";
    message: string;
    reason?: MCPOAuthFailureReason;
  } | null>(null);

  const isOAuthEnabled = useOAuthPassThroughEnabled();
  const authMethods = {
    [MCPAuthenticationType.OAUTH]: {
      label: t("mcpAuthModal.authType.oauth.label"),
      title: t("mcpAuthModal.oauthInfo.title"),
      description: t("mcpAuthModal.oauthInfo.discovery", { appName }),
    },
    [MCPAuthenticationType.API_TOKEN]: {
      label: t("mcpAuthModal.authType.apiToken.label"),
      title: t("mcpAuthModal.apiTokenInfo.title"),
      description: t("mcpAuthModal.apiTokenInfo.description"),
    },
    [MCPAuthenticationType.NONE]: {
      label: t("mcpAuthModal.authType.none.label"),
      title: t("mcpAuthModal.noAuthNotice.title"),
      description: t("mcpAuthModal.noAuthNotice.description"),
    },
    [MCPAuthenticationType.PT_OAUTH]: {
      label: t("mcpAuthModal.authType.ptOauth.label"),
      title: t("mcpAuthModal.passThroughNotice.title"),
      description: t("mcpAuthModal.passThroughNotice.description", { appName }),
    },
  } satisfies Record<
    MCPAuthenticationType,
    { label: string; title: string; description: string }
  >;

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
        oauth_client_id: Yup.string().when(["auth_type", "oauth_setup_mode"], {
          is: (authType: string, setupMode: string) =>
            authType === MCPAuthenticationType.OAUTH &&
            setupMode === "own_client",
          then: (schema) =>
            schema.required(t("mcpAuthModal.clientId.required")),
          otherwise: (schema) => schema.notRequired(),
        }),
        oauth_client_secret: Yup.string().notRequired(),
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

  const {
    data: oauthDiscovery,
    error: oauthDiscoveryError,
    isLoading: isDiscoveringOAuth,
    isValidating: isRevalidatingOAuth,
    mutate: retryOAuthDiscovery,
  } = useSWR(
    [
      ...SWR_KEYS.adminMcpOAuthDiscovery(mcpServer.id),
      mcpServer.server_url,
    ] as const,
    ([, serverId]) => discoverMCPOAuth(serverId),
    {
      revalidateOnMount: true,
      revalidateOnFocus: false,
      shouldRetryOnError: false,
    }
  );

  const handleSubmit = async (
    values: MCPAuthFormValues,
    helpers: FormikHelpers<MCPAuthFormValues>
  ) => {
    if (readOnly) return;
    setIsSubmitting(true);
    setConnectionError(null);
    let stage: "saveStage" | "oauthStage" | "discoveryStage" = "saveStage";

    try {
      // Keep validation failures visible without clearing the form.
      const comparisonValues = persistedValues.current ?? initialValues;
      const serverData = buildMCPAuthPayload(
        values,
        comparisonValues,
        mcpServer,
        t
      );

      const authType = values.auth_type;
      // Step 1: Save the authentication configuration to the MCP server
      const { data: serverResult, error: serverError } =
        await upsertMCPServer(serverData);

      if (serverError || !serverResult) {
        throw new Error(
          serverError || t("mcpAuthModal.errors.saveConfigFailed")
        );
      }

      persistedValues.current = values;
      helpers.resetForm({ values });
      await onSaved().catch((error: unknown) => {
        console.error("Error refreshing MCP servers:", error);
      });

      // Step 2: Update status to AWAITING_AUTH after successful config save
      if (authType === MCPAuthenticationType.OAUTH) {
        await updateMCPServerStatus(
          mcpServer.id,
          MCPServerStatus.AWAITING_AUTH
        );
      }

      // Step 3: For OAuth, initiate the OAuth flow
      if (authType === MCPAuthenticationType.OAUTH) {
        stage = "oauthStage";
        const oauthStart = await startMCPAdminOAuth(
          mcpServer.id,
          `${ADMIN_ROUTES.MCP_ACTIONS.path}/${mcpServer.id}?trigger_fetch=true`,
          {
            oauth_client_id: values.oauth_client_id,
            oauth_client_secret: values.oauth_client_secret,
            oauth_client_id_changed: serverData.oauth_client_id_changed,
            oauth_client_secret_changed: serverData.oauth_client_secret_changed,
          }
        );
        if (
          oauthStart.status === "already_authenticated" &&
          onTriggerFetchTools
        ) {
          stage = "discoveryStage";
          await onTriggerFetchTools(mcpServer.id);
          await onComplete();
        } else {
          window.location.href = getMCPUserOAuthNavigationUrl(oauthStart);
        }
      } else {
        // For non-OAuth authentication, trigger tools fetch in-place (no hard navigation)
        if (onTriggerFetchTools) {
          stage = "discoveryStage";
          await onTriggerFetchTools(mcpServer.id);
        } else {
          // Fallback to previous behavior if parent didn't provide handler
          window.location.href = `${ADMIN_ROUTES.MCP_ACTIONS.path}/${mcpServer.id}?trigger_fetch=true`;
        }
        await onComplete();
      }
    } catch (error) {
      console.error("Error saving authentication:", error);
      const oauthErrorMessages = {
        client_registration_failed: t(
          "mcpAuthModal.errors.clientRegistrationFailed"
        ),
        discovery_failed: t("mcpAuthModal.errors.discoveryFailed"),
        connection_failed: t("mcpAuthModal.errors.connectionFailed"),
        oauth_failed: t("mcpAuthModal.errors.oauthFailed"),
      } satisfies Record<MCPOAuthFailureReason, string>;
      setConnectionError({
        stage,
        reason: error instanceof MCPOAuthError ? error.reason : undefined,
        message:
          error instanceof MCPOAuthError
            ? oauthErrorMessages[error.reason]
            : error instanceof Error
              ? error.message
              : t("mcpAuthModal.errors.saveAuthFailed"),
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Formik<MCPAuthFormValues>
      initialValues={initialValues}
      validationSchema={validationSchema}
      validate={(values) => validateMCPAuthCredentials(values, t)}
      onSubmit={handleSubmit}
    >
      {({ values, setFieldValue, setValues, isValid }) => {
        return (
          <Form
            id={formId}
            className="flex min-h-0 min-w-0 w-full flex-1 flex-col gap-6"
          >
            <MCPFormDirtyObserver onDirtyChange={onDirtyChange} />
            <fieldset
              disabled={isSubmitting || readOnly}
              className="min-w-0 w-full"
            >
              <Section
                padding={variant === "page" ? 0 : 6}
                gap={6}
                alignItems="stretch"
              >
                <Tabs
                  value={values.auth_type}
                  gap={6}
                  onValueChange={(value) => {
                    const authType = Object.values(MCPAuthenticationType).find(
                      (type) => type === value
                    );
                    if (!authType) return;
                    setConnectionError(null);
                    const performer =
                      authType === MCPAuthenticationType.OAUTH ||
                      authType === MCPAuthenticationType.PT_OAUTH
                        ? MCPAuthenticationPerformer.PER_USER
                        : values.auth_performer;
                    const scopeChanged = performer !== values.auth_performer;
                    setValues({
                      ...values,
                      auth_type: authType,
                      auth_performer: performer,
                      auth_template: getAuthTemplateForMethod(
                        values.auth_template,
                        authType
                      ),
                      oauth_provider_mode:
                        authType === MCPAuthenticationType.OAUTH
                          ? values.oauth_provider_mode
                          : MCPOAuthProviderMode.AUTO_DISCOVERY,
                      api_token: scopeChanged ? "" : values.api_token,
                      user_credentials: scopeChanged
                        ? {}
                        : values.user_credentials,
                    });
                  }}
                >
                  <div className="w-full min-w-0 overflow-x-auto">
                    <div className="w-full min-w-max">
                      <Tabs.List>
                        {[
                          MCPAuthenticationType.PT_OAUTH,
                          MCPAuthenticationType.OAUTH,
                          MCPAuthenticationType.API_TOKEN,
                          MCPAuthenticationType.NONE,
                        ]
                          .filter(
                            (type) =>
                              type !== MCPAuthenticationType.PT_OAUTH ||
                              isOAuthEnabled
                          )
                          .map((type) => (
                            <Tabs.Trigger key={type} value={type}>
                              {authMethods[type].label}
                            </Tabs.Trigger>
                          ))}
                      </Tabs.List>
                    </div>
                  </div>
                  <Tabs.Content value={values.auth_type}>
                    <Section alignItems="stretch" height="auto" gap={6}>
                      <Content
                        sizePreset="main-content"
                        variant="section"
                        title={authMethods[values.auth_type].title}
                        description={authMethods[values.auth_type].description}
                      />
                      {values.auth_type === MCPAuthenticationType.OAUTH && (
                        <MCPOAuthFields
                          discovery={oauthDiscovery}
                          checking={isDiscoveringOAuth || isRevalidatingOAuth}
                          failed={!!oauthDiscoveryError}
                          onRetry={() => {
                            void retryOAuthDiscovery();
                          }}
                          redirectUri={redirectUri}
                          onSettingsChange={() => setConnectionError(null)}
                        />
                      )}
                      {/* API Key Section with Tabs */}
                      {values.auth_type === MCPAuthenticationType.API_TOKEN && (
                        <MCPApiTokenFields
                          onSettingsChange={() => setConnectionError(null)}
                        />
                      )}
                      {values.auth_type !== MCPAuthenticationType.API_TOKEN && (
                        <PerUserAuthConfig
                          section="credentials"
                          values={values}
                          setFieldValue={setFieldValue}
                        />
                      )}
                      <MCPAdvancedFields
                        open={connectionSettingsOpen}
                        onOpenChange={setConnectionSettingsOpen}
                      />
                    </Section>
                  </Tabs.Content>
                </Tabs>
                {connectionError && (
                  <div role="alert">
                    <MessageCard
                      variant="error"
                      outerPadding={1}
                      innerPadding={1}
                      title={t(`mcpAuthModal.errors.${connectionError.stage}`)}
                      description={connectionError.message}
                    />
                    {connectionError.reason ===
                      "client_registration_failed" && (
                      <Button
                        type="button"
                        prominence="secondary"
                        onClick={() => {
                          setFieldValue("oauth_setup_mode", "own_client");
                          setConnectionError(null);
                        }}
                      >
                        {t("mcpAuthModal.discovery.useOwnClient")}
                      </Button>
                    )}
                    {connectionError.reason === "discovery_failed" && (
                      <Button
                        type="button"
                        prominence="secondary"
                        onClick={() => {
                          setValues({
                            ...values,
                            oauth_setup_mode: "own_client",
                            oauth_provider_mode:
                              MCPOAuthProviderMode.KNOWN_PROVIDER,
                          });
                          setConnectionError(null);
                        }}
                      >
                        {t("mcpAuthModal.discovery.manual")}
                      </Button>
                    )}
                  </div>
                )}
              </Section>
            </fieldset>

            {!readOnly && (
              <MCPFormActions
                variant={variant}
                active={active}
                footerTarget={footerTarget}
                back={
                  onBack && (
                    <Button
                      prominence="tertiary"
                      type="button"
                      disabled={isSubmitting}
                      icon={SvgArrowLeft}
                      onClick={onBack}
                    >
                      {t("mcpSetup.back")}
                    </Button>
                  )
                }
                cancel={
                  <Button
                    prominence="secondary"
                    type="button"
                    disabled={isSubmitting}
                    onClick={onCancel}
                  >
                    {t("addMcpModal.cancelButton.label")}
                  </Button>
                }
                submit={
                  <Button
                    disabled={
                      !isValid ||
                      isSubmitting ||
                      (values.auth_type === MCPAuthenticationType.OAUTH &&
                        values.oauth_setup_mode === "automatic" &&
                        (isDiscoveringOAuth || isRevalidatingOAuth))
                    }
                    type="submit"
                    form={formId}
                    data-testid="mcp-auth-connect-button"
                  >
                    {isSubmitting
                      ? t("mcpAuthModal.submitButton.pendingLabel")
                      : t("mcpAuthModal.submitButton.label")}
                  </Button>
                }
              />
            )}
          </Form>
        );
      }}
    </Formik>
  );
}
