"use client";

import {
  useId,
  useState,
  useMemo,
  useEffect,
  useRef,
  type ReactNode,
} from "react";
import { useTranslations } from "next-intl";
import type { MCPAuthFormValues } from "@/sections/actions/modals/types";
import {
  getMCPAuthInitialValues,
  getAuthTemplateForMethod,
  prepareMCPAuthPayload,
  MCPAuthValidationError,
  validateMCPAuthCredentials,
} from "@/sections/actions/modals/mcpAuthForm";
import { mcpOAuthReturnHref } from "@/lib/plugins/routes";
import { useUser } from "@/providers/UserProvider";
import {
  clearMcpChatEnableIntent,
  mintMcpChatEnableIntent,
} from "@/sections/actions/mcpChatEnableIntent";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { SvgArrowLeft } from "@opal/icons";
import { InputVertical, Section } from "@opal/layouts";
import {
  Button,
  InputSingleSelect,
  MessageCard,
  Tag,
  Text,
} from "@opal/components";
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
  type MCPSetupRecommendation,
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
import { MCPOAuthFields } from "@/sections/actions/modals/MCPOAuthFields";
import { MCPApiTokenFields } from "@/sections/actions/modals/MCPApiTokenFields";
import { MCPAdvancedFields } from "@/sections/actions/modals/MCPAdvancedFields";
import { useOAuthPassThroughEnabled } from "@/lib/auth/hooks";

import MCPFormActions from "@/sections/actions/modals/MCPFormActions";
import MCPFormDirtyObserver from "@/sections/actions/modals/MCPFormDirtyObserver";

interface MCPAuthenticationPageBaseProps {
  active: boolean;
  variant?: "modal" | "page";
  readOnly?: boolean;
  footerTarget?: HTMLDivElement | null;
  beforeFields?: ReactNode;
  canSubmit?: boolean;
  recommendation?: MCPSetupRecommendation;
  onTriggerFetchTools: (
    serverId: number,
    chatEnableIntent?: string | null
  ) => Promise<void> | void;
  onBusyChange: (busy: boolean) => void;
  onDirtyChange?: (dirty: boolean) => void;
  onCancel?: () => void;
  onSaved: () => Promise<void>;
  onBack?: () => void;
  onComplete: () => Promise<void> | void;
  enableChatOnConnect?: boolean;
  chatEnableIntent?: string | null;
}

type MCPAuthenticationPageProps = MCPAuthenticationPageBaseProps &
  (
    | { mcpServer: MCPServer; resolveServer?: never }
    | {
        mcpServer: Pick<MCPServer, "name" | "description" | "server_url">;
        resolveServer: () => Promise<MCPServer>;
      }
  );

export default function MCPAuthenticationPage({
  active,
  variant = "modal",
  readOnly = false,
  footerTarget = null,
  mcpServer,
  resolveServer,
  beforeFields,
  canSubmit = true,
  recommendation,
  onTriggerFetchTools,
  onBusyChange,
  onDirtyChange,
  onCancel,
  onSaved,
  onBack,
  onComplete,
  enableChatOnConnect = false,
  chatEnableIntent = null,
}: MCPAuthenticationPageProps) {
  const formId = useId();
  const t = useTranslations("actions");
  const recommendedCopy = useTranslations("craft.llmPopover.recommended");
  const { appName } = useSettings();
  const { user } = useUser();
  const [initialValues] = useState(() => {
    const values = getMCPAuthInitialValues(mcpServer);
    if (!recommendation) return values;
    return {
      ...values,
      transport: recommendation.transport ?? values.transport,
      auth_type:
        recommendation.kind === "public"
          ? MCPAuthenticationType.NONE
          : MCPAuthenticationType.OAUTH,
      auth_performer: MCPAuthenticationPerformer.PER_USER,
      oauth_setup_mode:
        recommendation.kind === "oauth" &&
        recommendation.discovery.supports_automatic_registration === false
          ? ("own_client" as const)
          : ("automatic" as const),
    };
  });
  const [selectedAuthentication, setSelectedAuthentication] =
    useState<MCPAuthenticationType | null>(
      recommendation?.kind === "auth_unknown" ? null : initialValues.auth_type
    );
  const persistedValues = useRef(initialValues);
  const [hasChosenSetup, setHasChosenSetup] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  useEffect(() => onBusyChange(isSubmitting), [isSubmitting, onBusyChange]);
  const [connectionSettingsOpen, setConnectionSettingsOpen] = useState(false);
  const [connectionError, setConnectionError] = useState<{
    stage: "saveStage" | "oauthStage" | "discoveryStage";
    message: string;
    reason?: MCPOAuthFailureReason;
  } | null>(null);

  const isOAuthEnabled = useOAuthPassThroughEnabled();
  const recommendedAuthentication =
    recommendation?.kind === "public"
      ? MCPAuthenticationType.NONE
      : recommendation?.kind === "oauth"
        ? MCPAuthenticationType.OAUTH
        : null;
  const authMethods = {
    [MCPAuthenticationType.OAUTH]: {
      label: t("mcpAuthModal.authType.oauth.label"),
      description: t("mcpAuthModal.oauthInfo.discovery", { appName }),
    },
    [MCPAuthenticationType.API_TOKEN]: {
      label: t("mcpAuthModal.authType.apiToken.label"),
      description: t("mcpAuthModal.apiTokenInfo.description"),
    },
    [MCPAuthenticationType.NONE]: {
      label: t("mcpAuthModal.authType.none.label"),
      description: t("mcpAuthModal.noAuthNotice.description"),
    },
    [MCPAuthenticationType.PT_OAUTH]: {
      label: t("mcpAuthModal.authType.ptOauth.label"),
      description: t("mcpAuthModal.passThroughNotice.description", { appName }),
    },
  } satisfies Record<
    MCPAuthenticationType,
    { label: string; description: string }
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
    !("id" in mcpServer) ||
      recommendation?.kind === "oauth" ||
      (recommendation && selectedAuthentication !== MCPAuthenticationType.OAUTH)
      ? null
      : ([
          ...SWR_KEYS.adminMcpOAuthDiscovery(mcpServer.id),
          mcpServer.server_url,
        ] as const),
    ([, serverId]) => discoverMCPOAuth(serverId),
    {
      revalidateOnMount: true,
      revalidateOnFocus: false,
      shouldRetryOnError: false,
      fallbackData:
        recommendation?.kind === "oauth" ? recommendation.discovery : undefined,
    }
  );

  const handleSubmit = async (
    values: MCPAuthFormValues,
    helpers: FormikHelpers<MCPAuthFormValues>
  ) => {
    if (readOnly || selectedAuthentication === null) return;
    setIsSubmitting(true);
    setConnectionError(null);
    let stage: "saveStage" | "oauthStage" | "discoveryStage" = "saveStage";
    let enableIntent = chatEnableIntent;

    try {
      const comparisonValues = persistedValues.current ?? initialValues;
      const authData = prepareMCPAuthPayload(values, comparisonValues, t);
      const savedServer = resolveServer ? await resolveServer() : mcpServer;
      if (resolveServer && enableChatOnConnect) {
        enableIntent = mintMcpChatEnableIntent({
          userId: user?.id,
          serverId: savedServer.id,
        });
        if (!enableIntent)
          throw new Error(t("addMcpModal.toasts.updateFailed"));
      }
      const serverData = {
        ...authData,
        name: savedServer.name,
        description: savedServer.description || undefined,
        server_url: savedServer.server_url,
        existing_server_id: savedServer.id,
      };

      const authType = values.auth_type;
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

      if (authType === MCPAuthenticationType.OAUTH) {
        await updateMCPServerStatus(
          savedServer.id,
          MCPServerStatus.AWAITING_AUTH
        );
      }

      if (authType === MCPAuthenticationType.OAUTH) {
        stage = "oauthStage";
        const oauthStart = await startMCPAdminOAuth(
          savedServer.id,
          enableIntent
            ? `${mcpOAuthReturnHref(savedServer.id, true)}&enable_chat_intent=${encodeURIComponent(enableIntent)}`
            : mcpOAuthReturnHref(savedServer.id),
          {
            oauth_client_id: values.oauth_client_id,
            oauth_client_secret: values.oauth_client_secret,
            oauth_client_id_changed: serverData.oauth_client_id_changed,
            oauth_client_secret_changed: serverData.oauth_client_secret_changed,
          }
        );
        if (oauthStart.status !== "already_authenticated") {
          window.location.href = getMCPUserOAuthNavigationUrl(oauthStart);
          return;
        }
      }
      stage = "discoveryStage";
      if (enableIntent) await onTriggerFetchTools(savedServer.id, enableIntent);
      else await onTriggerFetchTools(savedServer.id);
      await onComplete();
    } catch (error) {
      // The caller's intent must survive for retries; it clears it on cancel.
      if (enableIntent !== chatEnableIntent)
        clearMcpChatEnableIntent(enableIntent);
      if (error instanceof MCPAuthValidationError) {
        helpers.setFieldError("oauth_additional_auth_params", error.message);
      }
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
      validateOnMount={!!recommendation}
      validate={(values) => validateMCPAuthCredentials(values, t)}
      onSubmit={handleSubmit}
    >
      {({ values, setFieldValue, setValues, isValid }) => {
        return (
          <Form
            id={formId}
            className="flex min-h-0 min-w-0 w-full flex-1 flex-col gap-6"
          >
            {onDirtyChange && (
              <MCPFormDirtyObserver onDirtyChange={onDirtyChange} />
            )}
            <fieldset
              disabled={isSubmitting || readOnly}
              className="min-w-0 w-full"
            >
              <Section
                padding={variant === "page" ? 0 : 6}
                gap={resolveServer ? 4 : 6}
                alignItems="stretch"
              >
                {beforeFields}
                {recommendation && !resolveServer && (
                  <Section alignItems="stretch" height="auto" gap={2}>
                    <Text font="main-content-emphasis">{mcpServer.name}</Text>
                    <Text font="secondary-body" color="text-03">
                      {mcpServer.server_url}
                    </Text>
                    <MessageCard
                      variant={
                        recommendation.kind === "auth_unknown"
                          ? "warning"
                          : "success"
                      }
                      title={t(
                        `mcpSetup.${recommendation.kind === "public" ? "publicDetected" : recommendation.kind === "oauth" ? "oauthDetected" : "manualRequired"}`
                      )}
                      description={
                        recommendation.kind === "auth_unknown"
                          ? t("mcpSetup.chooseAuthentication")
                          : recommendation.kind === "public"
                            ? t("mcpSetup.publicDetails", {
                                count: recommendation.tool_count,
                              })
                            : undefined
                      }
                      outerPadding={1}
                      innerPadding={1}
                    />
                  </Section>
                )}
                <Section alignItems="stretch" height="auto" gap={4}>
                  <InputVertical title={t("mcpAuthModal.authType.label")}>
                    <InputSingleSelect
                      disabled={isSubmitting || readOnly}
                      value={selectedAuthentication ?? ""}
                      defaultOption={selectedAuthentication ?? undefined}
                      placeholder={t("mcpAuthModal.authType.label")}
                      rightChildren={
                        selectedAuthentication !== null &&
                        selectedAuthentication === recommendedAuthentication ? (
                          <Tag title={recommendedCopy("label")} color="green" />
                        ) : undefined
                      }
                      options={[
                        MCPAuthenticationType.OAUTH,
                        MCPAuthenticationType.API_TOKEN,
                        MCPAuthenticationType.NONE,
                        MCPAuthenticationType.PT_OAUTH,
                      ]
                        .filter(
                          (type) =>
                            type !== MCPAuthenticationType.PT_OAUTH ||
                            (isOAuthEnabled &&
                              (!recommendation ||
                                connectionSettingsOpen ||
                                selectedAuthentication ===
                                  MCPAuthenticationType.PT_OAUTH))
                        )
                        .map((type) => ({
                          value: type,
                          title: authMethods[type].label,
                          suffix:
                            type === recommendedAuthentication
                              ? recommendedCopy("label")
                              : undefined,
                        }))}
                      onValueChange={(value) => {
                        const authType = Object.values(
                          MCPAuthenticationType
                        ).find((type) => type === value);
                        if (!authType) return;
                        setSelectedAuthentication(authType);
                        setConnectionError(null);
                        const performer =
                          authType === MCPAuthenticationType.OAUTH ||
                          authType === MCPAuthenticationType.PT_OAUTH
                            ? MCPAuthenticationPerformer.PER_USER
                            : values.auth_performer;
                        const scopeChanged =
                          performer !== values.auth_performer;
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
                          oauth_cimd_enabled:
                            authType === MCPAuthenticationType.OAUTH
                              ? values.oauth_cimd_enabled
                              : true,
                          api_token: scopeChanged ? "" : values.api_token,
                          user_credentials: scopeChanged
                            ? {}
                            : values.user_credentials,
                        });
                      }}
                    />
                  </InputVertical>
                  {selectedAuthentication !== null && (
                    <Section
                      alignItems="stretch"
                      height="auto"
                      gap={resolveServer ? 4 : 6}
                    >
                      {!(
                        recommendation?.kind === "public" &&
                        values.auth_type === MCPAuthenticationType.NONE
                      ) && (
                        <Text font="secondary-body" color="text-03">
                          {authMethods[values.auth_type].description}
                        </Text>
                      )}
                      {values.auth_type === MCPAuthenticationType.OAUTH && (
                        <MCPOAuthFields
                          hasChosenSetup={hasChosenSetup}
                          onSetupChosen={() => setHasChosenSetup(true)}
                          disabled={isSubmitting || readOnly}
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
                      {values.auth_type === MCPAuthenticationType.API_TOKEN && (
                        <MCPApiTokenFields
                          disabled={isSubmitting || readOnly}
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
                  )}
                </Section>
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
                  onCancel && (
                    <Button
                      prominence="secondary"
                      type="button"
                      disabled={isSubmitting}
                      onClick={onCancel}
                    >
                      {t("addMcpModal.cancelButton.label")}
                    </Button>
                  )
                }
                submit={
                  <Button
                    disabled={
                      !canSubmit ||
                      !isValid ||
                      selectedAuthentication === null ||
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
                      : t(
                          recommendation
                            ? "mcpSetup.connect"
                            : "mcpAuthModal.submitButton.label"
                        )}
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
