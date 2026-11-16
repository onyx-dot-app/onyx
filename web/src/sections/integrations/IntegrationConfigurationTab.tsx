"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Card,
  InputPasswordTypeIn,
  InputSwitch,
  InputTextArea,
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
import { isSilentOAuthOutcome, launchOAuth } from "@/lib/oauth/launch";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  deleteOrganizationConnection,
  saveOrganizationConnection,
  startOrganizationOAuth,
  updateIntegration,
} from "@/lib/integrations/svc";
import type {
  AdminIntegrationDetail,
  AuthMethod,
  IntegrationConfig,
  IntegrationUpdate,
} from "@/lib/integrations/types";
import { integrationDetailHref } from "@/lib/integrations/utils";
import IntegrationSignInFields from "@/sections/integrations/IntegrationSignInFields";
import { normalizedServerUrl } from "@/sections/integrations/McpServerFields";
import {
  signInDraftFromDetail,
  signInErrors,
  signInPayload,
  type SignInDraft,
} from "@/sections/integrations/signIn";

const METHODS: Record<AdminIntegrationDetail["shape"], readonly AuthMethod[]> =
  {
    mcp_server: ["oauth2", "api_key"],
    openapi: ["oauth2", "api_key", "onyx_login"],
    custom: ["oauth2", "api_key"],
    preset: ["oauth2", "api_key", "managed"],
  };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The schema text as an object, or `null` when it is not a JSON object. */
function parseSpec(text: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(text);
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

interface IntegrationConfigurationTabProps {
  integration: AdminIntegrationDetail;
  onChanged: () => void;
}

export default function IntegrationConfigurationTab({
  integration,
  onChanged,
}: IntegrationConfigurationTabProps) {
  const t = useTranslations("admin.integrations.detail.configuration");
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
  const [urlPatterns, setUrlPatterns] = useState(
    integration.config.shape === "custom"
      ? integration.config.upstream_url_patterns.join("\n")
      : ""
  );
  const initialSpec =
    integration.config.shape === "openapi"
      ? JSON.stringify(integration.config.openapi_spec, null, 2)
      : "";
  const [specText, setSpecText] = useState(initialSpec);
  const [alwaysAllow, setAlwaysAllow] = useState(
    integration.users_can_save_always_allow
  );
  const [fields, setFields] = useState<Record<string, string>>({});
  const [showErrors, setShowErrors] = useState(false);
  const [busy, setBusy] = useState(false);

  function nextConfig(): IntegrationConfig | null | undefined {
    const config = integration.config;
    if (config.shape === "mcp_server") {
      const url = normalizedServerUrl(serverUrl);
      if (!url) return null;
      return url === config.server_url
        ? undefined
        : { ...config, server_url: url };
    }
    if (config.shape === "custom") {
      const patterns = urlPatterns
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
      if (!patterns.length) return null;
      return patterns.join("\n") === config.upstream_url_patterns.join("\n")
        ? undefined
        : { shape: "custom", upstream_url_patterns: patterns };
    }
    if (config.shape === "openapi") {
      if (specText === initialSpec) return undefined;
      const spec = parseSpec(specText);
      return spec ? { shape: "openapi", openapi_spec: spec } : null;
    }
    return undefined;
  }

  async function refresh() {
    await mutate(SWR_KEYS.adminIntegrations);
    onChanged();
  }

  async function save() {
    const config = nextConfig();
    if (config === null || signInErrors(signIn).length > 0) {
      setShowErrors(true);
      return;
    }
    setBusy(true);
    try {
      const update: IntegrationUpdate = {
        ...signInPayload(signIn),
        users_can_save_always_allow: alwaysAllow,
      };
      if (config) update.config = config;
      await updateIntegration(integration.id, update);
      toast.success(t("saved"));
      await refresh();
    } catch (error) {
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

  function connectWithOAuth() {
    setBusy(true);
    launchOAuth(() =>
      startOrganizationOAuth(
        integration.id,
        integrationDetailHref(integration.id, "configuration")
      )
    )
      .then(async () => {
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
      {integration.config.shape !== "preset" && (
        <Card padding={4}>
          <Section gap={4} alignItems="stretch" height="auto">
            <Content font="main-ui-action" title={t("connection.title")} />
            {integration.config.shape === "mcp_server" ? (
              <InputVertical
                title={t("connection.serverUrl")}
                error={
                  showErrors && !normalizedServerUrl(serverUrl)
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
            ) : integration.config.shape === "openapi" ? (
              <InputVertical
                title={t("connection.schema")}
                description={t("connection.schemaDescription")}
                error={
                  showErrors && !parseSpec(specText)
                    ? t("connection.schemaError")
                    : undefined
                }
              >
                <InputTextArea
                  aria-label={t("connection.schema")}
                  value={specText}
                  rows={12}
                  variant={disabled ? "disabled" : "primary"}
                  onChange={(event) => setSpecText(event.target.value)}
                />
              </InputVertical>
            ) : (
              <InputVertical
                title={t("connection.urlPatterns")}
                description={t("connection.urlPatternsDescription")}
              >
                <InputTextArea
                  aria-label={t("connection.urlPatterns")}
                  value={urlPatterns}
                  rows={3}
                  variant={disabled ? "disabled" : "primary"}
                  onChange={(event) => setUrlPatterns(event.target.value)}
                />
              </InputVertical>
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
            methods={METHODS[integration.shape]}
            providerModes={
              integration.shape === "preset"
                ? ["preset", "manual"]
                : ["manual", "discovery"]
            }
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
            <Button disabled={disabled} onClick={() => void save()}>
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
              {t("organization.state", {
                state: organizationState ?? "not_set_up",
              })}
            </Text>
            {organizationState !== "connected" &&
              integration.auth_method === "api_key" &&
              integration.credential_fields.map((field) => (
                <InputVertical key={field.key} title={field.label}>
                  {field.secret ? (
                    <InputPasswordTypeIn
                      aria-label={field.label}
                      value={fields[field.key] ?? ""}
                      disabled={disabled}
                      onChange={(event) =>
                        setFields((current) => ({
                          ...current,
                          [field.key]: event.target.value,
                        }))
                      }
                    />
                  ) : (
                    <InputTypeIn
                      aria-label={field.label}
                      value={fields[field.key] ?? ""}
                      variant={disabled ? "disabled" : "primary"}
                      onChange={(event) =>
                        setFields((current) => ({
                          ...current,
                          [field.key]: event.target.value,
                        }))
                      }
                    />
                  )}
                </InputVertical>
              ))}
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
                  <Button disabled={disabled} onClick={connectWithOAuth}>
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
    </Section>
  );
}
