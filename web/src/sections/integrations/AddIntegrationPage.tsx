"use client";

import { useState, type FormEvent } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import {
  Button,
  Card,
  InputSingleSelect,
  InputTextArea,
  InputTypeIn,
  MessageCard,
  Modal,
  SelectCard,
  Text,
} from "@opal/components";
import {
  Content,
  InputVertical,
  Section,
  SettingsLayouts,
  toast,
} from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { SvgCodeFile, SvgPlug } from "@opal/icons";
import { useNavigation } from "@opal/navigation";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { customizeTabHref, integrationHref } from "@/lib/customize/paths";
import { integrationDetailHref } from "@/lib/integrations/utils";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import { BackLink } from "@/sections/customize/CustomizeDetailLayout";
import PluginModalContent from "@/sections/plugins/PluginModalContent";
import AddOpenAPIActionModal from "@/sections/actions/modals/AddOpenAPIActionModal";
import McpServerFields from "@/sections/integrations/McpServerFields";
import IntegrationSignInFields from "@/sections/integrations/IntegrationSignInFields";
import CredentialFieldInputs from "@/sections/integrations/CredentialFieldInputs";
import { INTEGRATION_SHAPE_ICONS } from "@/sections/integrations/integrationLabels";
import {
  DEFAULT_SIGN_IN,
  normalizedUrl,
  parseUrlPatterns,
  SIGN_IN_METHODS,
  signInErrors,
  signInPayload,
  type SignInDraft,
} from "@/sections/integrations/signIn";
import { createIntegration } from "@/lib/integrations/svc";
import { useSettings } from "@/lib/settings/hooks";
import { useIntegrationPresets } from "@/lib/integrations/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  AuthMethod,
  IntegrationConfig,
  IntegrationShape,
  McpTransport,
} from "@/lib/integrations/types";
import type { MCPSetupProbeResult } from "@/lib/mcp/types";

/** An app is a preset or a custom app; a preset fills in the app's fields. */
type IntegrationType = "mcp_server" | "openapi" | "app";

const CUSTOM_APP = "custom";

interface AddIntegrationPageProps {
  /** Admin adds to either library; Customize adds to the user's own. */
  from: "admin" | "customize";
}

export default function AddIntegrationPage({ from }: AddIntegrationPageProps) {
  const t = useTranslations("admin.integrations.add");
  const tabCopy = useTranslations("customize.tabs");
  const listCopy = useTranslations("admin.integrations");
  const navigation = useNavigation();
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_ACTIONS);
  const canChooseOrganization = from === "admin" && isGlobalHolder;
  const { mutate } = useSWRConfig();
  const backHref =
    from === "admin"
      ? ADMIN_ROUTES.INTEGRATIONS.path
      : customizeTabHref("integrations");
  const settings = useSettings();
  const types: IntegrationType[] =
    settings.onyx_craft_available === true
      ? ["mcp_server", "openapi", "app"]
      : ["mcp_server", "openapi"];
  const [type, setType] = useState<IntegrationType>("mcp_server");
  const [busy, setBusy] = useState(false);
  const [schemaOpen, setSchemaOpen] = useState(false);
  const [schemaBusy, setSchemaBusy] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [forOrganization, setForOrganization] = useState(false);
  const [signIn, setSignIn] = useState<SignInDraft>(DEFAULT_SIGN_IN);
  const [signInTouched, setSignInTouched] = useState(false);
  const [serverUrl, setServerUrl] = useState("");
  const [transport, setTransport] = useState<McpTransport>("STREAMABLE_HTTP");
  const [openapiSpec, setOpenapiSpec] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [appSource, setAppSource] = useState(CUSTOM_APP);
  const [orgCredentials, setOrgCredentials] = useState<Record<string, string>>(
    {}
  );
  const [urlPatterns, setUrlPatterns] = useState("");
  const presets = useIntegrationPresets(type === "app");
  const preset =
    type === "app"
      ? presets.data?.find((option) => option.id === appSource)
      : undefined;
  const shape: IntegrationShape =
    type === "app" ? (preset ? "preset" : "custom") : type;
  const methods: readonly AuthMethod[] =
    shape === "preset"
      ? (preset?.auth_methods.flatMap((method) => (method ? [method] : [])) ??
        [])
      : SIGN_IN_METHODS[shape];

  // Each type has its own sign-in methods, so a new type starts sign-in over.
  function pickType(next: IntegrationType) {
    if (next === type) return;
    setType(next);
    setShowErrors(false);
    setSignIn(DEFAULT_SIGN_IN);
    setSignInTouched(false);
    setAppSource(CUSTOM_APP);
    setOrgCredentials({});
  }

  function changeSignIn(next: SignInDraft) {
    setSignInTouched(true);
    setSignIn(next);
  }

  function applyProbe(result: MCPSetupProbeResult) {
    if (result.kind !== "unreachable" && result.transport)
      setTransport(result.transport);
    if (result.kind === "public" && !name.trim()) setName(result.server_name);
    if (signInTouched) return;
    if (result.kind === "public")
      setSignIn({ ...DEFAULT_SIGN_IN, authMode: "none" });
    else if (result.kind === "oauth")
      setSignIn({
        ...DEFAULT_SIGN_IN,
        authMode: "individual",
        authMethod: "oauth2",
        providerMode: result.discovery.supports_automatic_registration
          ? "discovery"
          : "manual",
        authorizationUrl: result.discovery.authorization_endpoint ?? "",
        tokenUrl: result.discovery.token_endpoint ?? "",
      });
    else if (result.kind === "auth_unknown")
      setSignIn({
        ...DEFAULT_SIGN_IN,
        authMode: "individual",
        authMethod: "api_key",
      });
  }

  function pickAppSource(id: string) {
    setAppSource(id);
    setOrgCredentials({});
    setSignInTouched(false);
    const next = presets.data?.find((option) => option.id === id);
    if (!next) {
      setSignIn(DEFAULT_SIGN_IN);
      return;
    }
    setName(next.name);
    const first = next.auth_methods.find((method) => method !== null);
    setSignIn({
      ...DEFAULT_SIGN_IN,
      authMode: first ? "individual" : "none",
      authMethod: first ?? null,
      providerMode: "preset",
    });
  }

  function config(): IntegrationConfig | null {
    switch (shape) {
      case "mcp_server": {
        const url = normalizedUrl(serverUrl);
        return url ? { shape: "mcp_server", server_url: url, transport } : null;
      }
      case "openapi":
        return openapiSpec
          ? { shape: "openapi", openapi_spec: openapiSpec }
          : null;
      case "preset": {
        if (!preset) return null;
        const missing = preset.required_org_credential_fields.some(
          (field) => !orgCredentials[field.key]?.trim()
        );
        if (missing) return null;
        return {
          shape: "preset",
          preset_id: preset.id,
          organization_credentials: preset.required_org_credential_fields.length
            ? orgCredentials
            : null,
        };
      }
      case "custom": {
        const patterns = parseUrlPatterns(urlPatterns);
        return patterns.length
          ? { shape: "custom", upstream_url_patterns: patterns }
          : null;
      }
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = config();
    if (!name.trim() || !body || signInErrors(signIn).length > 0) {
      setShowErrors(true);
      return;
    }
    setBusy(true);
    try {
      const created = await createIntegration({
        for_organization: canChooseOrganization && forOrganization,
        name: name.trim(),
        description: description.trim() || null,
        ...signInPayload(signIn),
        config: body,
      });
      toast.success(t("created", { name: created.name }));
      // The detail page reads the new integration from the list.
      if (from === "admin") {
        await mutate(SWR_KEYS.adminIntegrations);
        navigation.go(
          integrationDetailHref(
            created.id,
            created.needs_setup ? "configuration" : "actions"
          )
        );
      } else {
        await mutate(SWR_KEYS.integrations);
        navigation.go(integrationHref(created.id, "configuration"));
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("createFailed"));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)}>
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header
          back={
            <BackLink
              to={backHref}
              label={
                from === "admin" ? listCopy("title") : tabCopy("integrations")
              }
            />
          }
          icon={SvgPlug}
          title={t("title")}
          description={t("description")}
          stackActionsOnMobile
          actions={[
            <Button
              key="cancel"
              type="button"
              prominence="secondary"
              disabled={busy}
              onClick={() => navigation.go(backHref)}
            >
              {t("cancel")}
            </Button>,
            <Button key="submit" type="submit" disabled={busy}>
              {busy ? t("adding") : t("submit")}
            </Button>,
          ]}
        />
        <SettingsLayouts.Body>
          <Section alignItems="stretch" height="auto">
            <Content
              font="main-content-emphasis"
              title={t("type.title")}
              description={t("type.description")}
            />
            <Section
              flexDirection="row"
              alignItems="stretch"
              height="auto"
              gap={2}
              wrap
              role="radiogroup"
              aria-label={t("type.title")}
            >
              {types.map((option) => (
                <Section
                  key={option}
                  height="auto"
                  alignItems="stretch"
                  grow={1}
                  basis={14}
                >
                  <SelectCard
                    padding={3}
                    role="radio"
                    aria-checked={type === option}
                    aria-label={t(`type.${option}.title`)}
                    state={type === option ? "selected" : "empty"}
                    disabled={busy}
                    onClick={() => pickType(option)}
                  >
                    <Content
                      icon={
                        INTEGRATION_SHAPE_ICONS[
                          option === "app" ? "preset" : option
                        ]
                      }
                      title={t(`type.${option}.title`)}
                      description={t(`type.${option}.description`)}
                    />
                  </SelectCard>
                </Section>
              ))}
            </Section>
          </Section>

          <Section alignItems="stretch" height="auto">
            <Content font="main-content-emphasis" title={t("details.title")} />
            <Card padding={2}>
              <Section gap={4} alignItems="stretch" height="auto">
                {type === "app" &&
                  (presets.isLoading ? (
                    <IconLoader />
                  ) : presets.error ? (
                    <MessageCard
                      variant="error"
                      title={t("preset.loadFailed")}
                    />
                  ) : (
                    <InputVertical
                      title={t("preset.title")}
                      description={t("preset.description")}
                    >
                      <InputSingleSelect
                        placeholder={t("preset.title")}
                        value={appSource}
                        disabled={busy}
                        options={[
                          { value: CUSTOM_APP, title: t("preset.custom") },
                          ...(presets.data ?? []).map((option) => ({
                            value: option.id,
                            title: option.name,
                          })),
                        ]}
                        onValueChange={pickAppSource}
                      />
                    </InputVertical>
                  ))}
                {preset?.setup_instructions && (
                  <MessageCard
                    variant="info"
                    title={t("preset.instructions")}
                    description={preset.setup_instructions}
                  />
                )}
                {type === "openapi" && (
                  <InputVertical
                    title={t("openapi.schema.title")}
                    description={
                      openapiSpec
                        ? t("openapi.schema.added", {
                            count: Object.keys(
                              typeof openapiSpec.paths === "object" &&
                                openapiSpec.paths !== null
                                ? openapiSpec.paths
                                : {}
                            ).length,
                          })
                        : t("openapi.schema.description")
                    }
                    error={
                      showErrors && !openapiSpec
                        ? t("openapi.schema.required")
                        : undefined
                    }
                  >
                    <Section width="auto" height="auto" alignItems="start">
                      <Button
                        type="button"
                        prominence="secondary"
                        icon={SvgCodeFile}
                        disabled={busy}
                        onClick={() => setSchemaOpen(true)}
                      >
                        {openapiSpec
                          ? t("openapi.schema.edit")
                          : t("openapi.schema.add")}
                      </Button>
                    </Section>
                  </InputVertical>
                )}
                <InputVertical
                  title={t("name.title")}
                  error={
                    showErrors && !name.trim() ? t("name.required") : undefined
                  }
                >
                  <InputTypeIn
                    aria-label={t("name.title")}
                    placeholder={t("name.placeholder")}
                    value={name}
                    variant={busy ? "disabled" : "primary"}
                    onChange={(event) => setName(event.target.value)}
                  />
                </InputVertical>
                <InputVertical
                  title={t("descriptionField.title")}
                  suffix="optional"
                >
                  <InputTextArea
                    aria-label={t("descriptionField.title")}
                    placeholder={t("descriptionField.placeholder")}
                    value={description}
                    rows={2}
                    variant={busy ? "disabled" : "primary"}
                    onChange={(event) => setDescription(event.target.value)}
                  />
                </InputVertical>
                {type === "mcp_server" && (
                  <McpServerFields
                    serverUrl={serverUrl}
                    transport={transport}
                    onServerUrlChange={setServerUrl}
                    onSuggestion={(suggestedName, url) => {
                      setName(suggestedName);
                      setServerUrl(url);
                    }}
                    onTransportChange={setTransport}
                    onProbed={applyProbe}
                    showErrors={showErrors}
                    disabled={busy}
                  />
                )}
                {shape === "custom" && (
                  <InputVertical
                    title={t("custom.patterns.title")}
                    description={t("custom.patterns.description")}
                    error={
                      showErrors && !config()
                        ? t("custom.patterns.required")
                        : undefined
                    }
                  >
                    <InputTextArea
                      aria-label={t("custom.patterns.title")}
                      placeholder={t("custom.patterns.placeholder")}
                      value={urlPatterns}
                      rows={3}
                      variant={busy ? "disabled" : "primary"}
                      onChange={(event) => setUrlPatterns(event.target.value)}
                    />
                  </InputVertical>
                )}
                {preset && (
                  <CredentialFieldInputs
                    fields={preset.required_org_credential_fields}
                    values={orgCredentials}
                    onChange={setOrgCredentials}
                    disabled={busy}
                    error={(field) =>
                      showErrors && !orgCredentials[field.key]?.trim()
                        ? t("preset.credentialRequired")
                        : undefined
                    }
                  />
                )}
                {canChooseOrganization ? (
                  <InputVertical
                    title={t("owner.title")}
                    description={
                      forOrganization
                        ? t("owner.organizationDescription")
                        : t("owner.personalDescription")
                    }
                  >
                    <InputSingleSelect
                      placeholder={t("owner.title")}
                      value={forOrganization ? "organization" : "personal"}
                      disabled={busy}
                      options={[
                        { value: "personal", title: t("owner.personal") },
                        {
                          value: "organization",
                          title: t("owner.organization"),
                        },
                      ]}
                      onValueChange={(value) =>
                        setForOrganization(value === "organization")
                      }
                    />
                  </InputVertical>
                ) : (
                  <Text as="p" font="secondary-body" color="text-03">
                    {t("owner.personalDescription")}
                  </Text>
                )}
              </Section>
            </Card>
          </Section>

          <Section alignItems="stretch" height="auto">
            <Content font="main-content-emphasis" title={t("signIn.title")} />
            <Card padding={2}>
              <Section gap={4} alignItems="stretch" height="auto">
                <IntegrationSignInFields
                  draft={signIn}
                  onChange={changeSignIn}
                  methods={methods}
                  shape={shape}
                  showErrors={showErrors}
                  disabled={busy}
                />
              </Section>
            </Card>
          </Section>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>

      {schemaOpen && (
        <Modal
          open
          onOpenChange={(open) => !open && !schemaBusy && setSchemaOpen(false)}
        >
          <PluginModalContent>
            <AddOpenAPIActionModal
              title={t("openapi.title")}
              initialDefinition={openapiSpec ?? undefined}
              initialDescription={description}
              onBusyChange={setSchemaBusy}
              onClose={() => setSchemaOpen(false)}
              onConfigureAuthentication={(draft) => {
                setOpenapiSpec(draft.definition);
                if (!name.trim()) setName(draft.name);
                setDescription(draft.description);
                setSchemaOpen(false);
              }}
            />
          </PluginModalContent>
        </Modal>
      )}
    </form>
  );
}
