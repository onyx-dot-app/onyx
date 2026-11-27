"use client";

import { useState } from "react";
import isEqual from "lodash/isEqual";
import { useTranslations } from "next-intl";
import {
  Button,
  Card,
  InputSwitch,
  InputTypeIn,
  MessageCard,
  Text,
} from "@opal/components";
import {
  Content,
  InputHorizontal,
  InputVertical,
  Section,
  toast,
} from "@opal/layouts";
import { useSWRConfig } from "swr";
import { connectWithOAuth } from "@/lib/integrations/connect";
import { isSilentOAuthOutcome } from "@/lib/oauth/launch";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  deleteOrganizationConnection,
  saveOrganizationConnection,
  startOrganizationOAuth,
  updateIntegration,
} from "@/lib/integrations/svc";
import { FetchError } from "@/lib/fetcher";
import type {
  AdminIntegrationDetail,
  AuthMethod,
  EndpointLineError,
  GraphQLConfig,
  IntegrationConfig,
  IntegrationUpdate,
} from "@/lib/integrations/types";
import { useIntegrationPresets } from "@/lib/integrations/hooks";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";
import UnsavedChangesModal from "@/sections/modals/UnsavedChangesModal";
import { integrationDetailHref } from "@/lib/integrations/utils";
import IntegrationSignInFields from "@/sections/integrations/IntegrationSignInFields";
import CredentialFieldInputs from "@/sections/integrations/CredentialFieldInputs";
import GraphQLFields from "@/sections/integrations/GraphQLFields";
import { restBaseUrl } from "@/sections/integrations/detectApi";
import RestEndpointFields, {
  restDraftFrom,
  type RestDraft,
} from "@/sections/integrations/RestEndpointFields";
import {
  normalizedUrl,
  presetAuthMethods,
  SIGN_IN_METHODS,
  signInDraftFromDetail,
  signInErrors,
  signInPayload,
  type SignInDraft,
} from "@/sections/integrations/signIn";

interface IntegrationConfigurationTabProps {
  integration: AdminIntegrationDetail;
  onChanged: () => Promise<AdminIntegrationDetail | undefined>;
}

export default function IntegrationConfigurationTab({
  integration,
  onChanged,
}: IntegrationConfigurationTabProps) {
  const t = useTranslations("admin.integrations.detail.configuration");
  const stateCopy = useTranslations("integrations");
  const { mutate } = useSWRConfig();
  const readOnly = !integration.can_manage;
  const [signIn, setSignIn] = useState<SignInDraft>(() =>
    signInDraftFromDetail(integration)
  );
  const [serverUrl, setServerUrl] = useState(
    integration.config.shape === "mcp_server"
      ? integration.config.server_url
      : ""
  );
  const savedRest =
    integration.config.shape === "openapi"
      ? restDraftFrom(integration.config)
      : { document: null, baseUrl: "", endpoints: "" };
  const [rest, setRest] = useState<RestDraft>(savedRest);
  const endpointsRequired = savedRest.endpoints.trim() !== "";
  const [lineErrors, setLineErrors] = useState<EndpointLineError[]>([]);
  const [graphql, setGraphql] = useState<GraphQLConfig | null>(
    integration.config.shape === "graphql" ? integration.config : null
  );
  const [alwaysAllow, setAlwaysAllow] = useState(
    integration.users_can_save_always_allow
  );
  const [fields, setFields] = useState<Record<string, string>>({});
  const [presetCredentials, setPresetCredentials] = useState<
    Record<string, string>
  >({});
  const [showErrors, setShowErrors] = useState(false);
  const [busy, setBusy] = useState(false);
  // A schema import or introspection in flight; Save waits for it.
  const [loadingSchema, setLoadingSchema] = useState(false);
  // A refused or failed import; Save would keep the old spec, so it waits.
  const [importError, setImportError] = useState<string | null>(null);
  const presets = useIntegrationPresets(integration.shape === "preset");
  const preset = presets.data?.find(
    (option) => option.id === integration.preset_id
  );
  const methods: readonly AuthMethod[] =
    integration.shape === "preset"
      ? preset
        ? presetAuthMethods(preset)
        : integration.auth_method
          ? [integration.auth_method]
          : []
      : SIGN_IN_METHODS[integration.shape];
  const savedSignIn = signInPayload(signInDraftFromDetail(integration));
  const signInChanged = !isEqual(signInPayload(signIn), savedSignIn);

  function nextConfig(): IntegrationConfig | null | undefined {
    const config = integration.config;
    if (config.shape === "mcp_server") {
      const url = normalizedUrl(serverUrl);
      if (!url) return null;
      return url === config.server_url
        ? undefined
        : { ...config, server_url: url };
    }
    if (config.shape === "custom") return undefined;
    if (config.shape === "graphql") {
      if (!graphql) return undefined;
      if (!graphql.endpoint_url.trim() || !graphql.graphql_schema.trim())
        return null;
      const next = { ...graphql, endpoint_url: graphql.endpoint_url.trim() };
      return isEqual(next, config) ? undefined : next;
    }
    if (config.shape === "openapi") {
      if (isEqual(rest, savedRest)) return undefined;
      const base = restBaseUrl(rest.baseUrl);
      // Blank lines would remove every action; a migrated app may have none.
      if (!base || (endpointsRequired && !rest.endpoints.trim())) return null;
      return {
        shape: "openapi",
        openapi_document: rest.document,
        base_url: base,
        endpoints: rest.endpoints.split("\n"),
      };
    }
    const filled = Object.fromEntries(
      Object.entries(presetCredentials).flatMap(([key, value]) =>
        value.trim() ? [[key, value.trim()]] : []
      )
    );
    if (!preset || Object.keys(filled).length === 0) return undefined;
    if (
      preset.required_org_credential_fields.some((field) => !filled[field.key])
    )
      return null;
    return {
      shape: "preset",
      preset_id: config.preset_id,
      organization_credentials: filled,
    };
  }

  const dirty =
    nextConfig() !== undefined ||
    signInChanged ||
    alwaysAllow !== integration.users_can_save_always_allow;
  const unsavedChanges = useUnsavedChangesGuard({ isDirty: dirty });

  async function refresh() {
    await mutate(SWR_KEYS.adminIntegrations);
    await onChanged();
  }

  async function save() {
    const config = nextConfig();
    if (config === null || (signInChanged && signInErrors(signIn).length > 0)) {
      setShowErrors(true);
      return;
    }
    setBusy(true);
    setLineErrors([]);
    try {
      const update: IntegrationUpdate = {
        users_can_save_always_allow: alwaysAllow,
      };
      // The sign-in fields replace the stored ones, so send them only on a
      // change.
      if (signInChanged) Object.assign(update, signInPayload(signIn));
      if (config) update.config = config;
      const saved = await updateIntegration(integration.id, update);
      // The response leaves out secrets and gives the schema as stored.
      setSignIn(signInDraftFromDetail(saved));
      if (saved.config.shape === "openapi")
        setRest(restDraftFrom(saved.config));
      if (saved.config.shape === "graphql") setGraphql(saved.config);
      setPresetCredentials({});
      toast.success(t("saved"));
      // A new schema or server syncs the actions again.
      if (config)
        await mutate(SWR_KEYS.adminIntegrationActions(integration.id));
      await refresh();
    } catch (error) {
      if (error instanceof FetchError)
        setLineErrors(error.info?.line_errors ?? []);
      toast.error(error instanceof Error ? error.message : t("saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function connectWithFields() {
    setBusy(true);
    try {
      await saveOrganizationConnection(integration.id, fields);
      setFields({});
      toast.success(t("organization.connected"));
      await refresh();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("organization.failed")
      );
    } finally {
      setBusy(false);
    }
  }

  function connectOrganization() {
    setBusy(true);
    connectWithOAuth(
      (path) => startOrganizationOAuth(integration.id, path),
      integrationDetailHref(integration.id, "configuration")
    )
      .then(async (result) => {
        if (result !== "connected") return;
        toast.success(t("organization.connected"));
        await refresh();
      })
      .catch((error: unknown) => {
        if (!isSilentOAuthOutcome(error)) toast.error(t("organization.failed"));
      })
      .finally(() => setBusy(false));
  }

  async function disconnect() {
    setBusy(true);
    try {
      await deleteOrganizationConnection(integration.id);
      toast.success(t("organization.disconnected"));
      await refresh();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("organization.failed")
      );
    } finally {
      setBusy(false);
    }
  }

  const organizationState = integration.organization_status?.state;
  const shared =
    integration.auth_mode === "shared" && integration.auth_method !== null;
  const disabled = busy || readOnly;

  return (
    <Section gap={4} alignItems="stretch" height="auto">
      {readOnly && (
        <Text font="secondary-body" color="text-03">
          {t("readOnly")}
        </Text>
      )}
      {integration.config.shape === "preset" &&
        preset &&
        preset.required_org_credential_fields.length > 0 && (
          <Card padding={4}>
            <Section gap={4} alignItems="stretch" height="auto">
              <Content
                font="main-ui-action"
                title={t("preset.title")}
                description={t("preset.description")}
              />
              <CredentialFieldInputs
                fields={preset.required_org_credential_fields}
                values={presetCredentials}
                onChange={setPresetCredentials}
                disabled={disabled}
                error={(field) =>
                  showErrors &&
                  nextConfig() === null &&
                  !presetCredentials[field.key]?.trim()
                    ? t("preset.credentialRequired")
                    : undefined
                }
              />
            </Section>
          </Card>
        )}
      {integration.config.shape !== "preset" &&
        integration.config.shape !== "custom" && (
          <Card padding={4}>
            <Section gap={4} alignItems="stretch" height="auto">
              <Content font="main-ui-action" title={t("connection.title")} />
              {integration.config.shape === "mcp_server" ? (
                <InputVertical
                  title={t("connection.serverUrl")}
                  error={
                    showErrors && !normalizedUrl(serverUrl)
                      ? t("connection.serverUrlError")
                      : undefined
                  }
                >
                  <InputTypeIn
                    aria-label={t("connection.serverUrl")}
                    value={serverUrl}
                    variant={disabled ? "disabled" : "primary"}
                    onChange={(event) => setServerUrl(event.target.value)}
                  />
                </InputVertical>
              ) : graphql ? (
                <GraphQLFields
                  draft={graphql}
                  onChange={setGraphql}
                  showErrors={showErrors}
                  disabled={disabled || loadingSchema}
                  onLoadingChange={setLoadingSchema}
                  importError={importError}
                  onImportErrorChange={setImportError}
                />
              ) : (
                <RestEndpointFields
                  draft={rest}
                  onChange={(next) => {
                    setRest(next);
                    setLineErrors([]);
                  }}
                  lineErrors={lineErrors}
                  showErrors={showErrors}
                  endpointsRequired={endpointsRequired}
                  disabled={disabled || loadingSchema}
                  onImportingChange={setLoadingSchema}
                  importError={importError}
                  onImportErrorChange={setImportError}
                />
              )}
            </Section>
          </Card>
        )}
      <Card padding={4}>
        <Section gap={4} alignItems="stretch" height="auto">
          <Content
            font="main-ui-action"
            title={t("signIn.title")}
            description={t("signIn.description")}
          />
          <IntegrationSignInFields
            draft={signIn}
            onChange={setSignIn}
            methods={methods}
            shape={integration.shape}
            showErrors={showErrors}
            disabled={disabled}
          />
          <InputHorizontal
            withLabel
            title={t("alwaysAllow.title")}
            description={t("alwaysAllow.description")}
            disabled={disabled}
          >
            <InputSwitch
              aria-label={t("alwaysAllow.title")}
              checked={alwaysAllow}
              disabled={disabled}
              onCheckedChange={setAlwaysAllow}
            />
          </InputHorizontal>
          <Section flexDirection="row" justifyContent="end" height="auto">
            <Button
              disabled={disabled || loadingSchema || importError !== null}
              onClick={() => void save()}
            >
              {busy ? t("saving") : t("save")}
            </Button>
          </Section>
        </Section>
      </Card>
      {shared && (
        <Card padding={4}>
          <Section gap={4} alignItems="stretch" height="auto">
            <Content
              font="main-ui-action"
              title={t("organization.title")}
              description={t("organization.description")}
            />
            {integration.organization_status?.reason && (
              <MessageCard
                variant="warning"
                title={integration.organization_status.reason}
              />
            )}
            <Text font="secondary-body" color="text-03">
              {stateCopy("connectionState", {
                state: organizationState ?? "not_set_up",
              })}
            </Text>
            {organizationState !== "connected" &&
              integration.auth_method === "api_key" && (
                <CredentialFieldInputs
                  fields={integration.credential_fields}
                  values={fields}
                  onChange={setFields}
                  disabled={disabled}
                />
              )}
            <Section
              flexDirection="row"
              justifyContent="end"
              gap={2}
              height="auto"
            >
              {organizationState === "connected" ||
              organizationState === "needs_reconnect" ? (
                <Button
                  prominence="secondary"
                  disabled={disabled}
                  onClick={() => void disconnect()}
                >
                  {t("organization.disconnect")}
                </Button>
              ) : null}
              {organizationState !== "connected" &&
                (integration.auth_method === "oauth2" ? (
                  <Button disabled={disabled} onClick={connectOrganization}>
                    {t("organization.connect")}
                  </Button>
                ) : integration.auth_method === "api_key" ? (
                  <Button
                    disabled={
                      disabled ||
                      integration.credential_fields.some(
                        (field) => !fields[field.key]?.trim()
                      )
                    }
                    onClick={() => void connectWithFields()}
                  >
                    {t("organization.connect")}
                  </Button>
                ) : null)}
            </Section>
          </Section>
        </Card>
      )}
      <UnsavedChangesModal
        open={unsavedChanges.confirmationOpen}
        onCancel={unsavedChanges.cancelLeave}
        onDiscard={unsavedChanges.discardAndLeave}
      />
    </Section>
  );
}
