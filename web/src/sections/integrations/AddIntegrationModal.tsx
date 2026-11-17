"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  BasicModalFooter,
  Button,
  InputSingleSelect,
  InputTextArea,
  InputTypeIn,
  MessageCard,
  Modal,
  SelectCard,
  Text,
} from "@opal/components";
import { Content, InputVertical, Section, toast } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { SvgBlocks, SvgCodeFile, SvgPlug, SvgServer } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import PluginModalContent from "@/sections/plugins/PluginModalContent";
import AddOpenAPIActionModal from "@/sections/actions/modals/AddOpenAPIActionModal";
import McpServerFields from "@/sections/integrations/McpServerFields";
import IntegrationSignInFields from "@/sections/integrations/IntegrationSignInFields";
import CredentialFieldInputs from "@/sections/integrations/CredentialFieldInputs";
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
import type {
  AdminIntegrationDetail,
  AuthMethod,
  IntegrationConfig,
  IntegrationShape,
  McpTransport,
} from "@/lib/integrations/types";
import type { MCPSetupProbeResult } from "@/lib/mcp/types";

const SHAPE_ICONS: Record<IntegrationShape, IconFunctionComponent> = {
  mcp_server: SvgServer,
  openapi: SvgCodeFile,
  preset: SvgBlocks,
  custom: SvgPlug,
};

type Step =
  | { kind: "pick" }
  | { kind: "openapiSchema" }
  | { kind: "form"; shape: IntegrationShape };

interface AddIntegrationModalProps {
  canChooseOrganization: boolean;
  onClose: () => void;
  onCreated: (integration: AdminIntegrationDetail) => void;
}

export default function AddIntegrationModal({
  canChooseOrganization,
  onClose,
  onCreated,
}: AddIntegrationModalProps) {
  const t = useTranslations("admin.integrations.add");
  const kindCopy = useTranslations("admin.integrations.shape");
  const settings = useSettings();
  const shapes: IntegrationShape[] =
    settings.onyx_craft_available === true
      ? ["mcp_server", "openapi", "preset", "custom"]
      : ["mcp_server", "openapi"];
  const [step, setStep] = useState<Step>({ kind: "pick" });
  const [busy, setBusy] = useState(false);
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
  const [presetId, setPresetId] = useState("");
  const [orgCredentials, setOrgCredentials] = useState<Record<string, string>>(
    {}
  );
  const [urlPatterns, setUrlPatterns] = useState("");
  const shape = step.kind === "form" ? step.shape : null;
  const presets = useIntegrationPresets(shape === "preset");
  const preset = presets.data?.find((option) => option.id === presetId);
  const presetMethods: AuthMethod[] =
    preset?.auth_methods.flatMap((method) => (method ? [method] : [])) ?? [];
  const methods =
    shape === "preset" ? presetMethods : shape ? SIGN_IN_METHODS[shape] : [];

  function close() {
    if (!busy) onClose();
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

  function pickPreset(id: string) {
    setPresetId(id);
    setOrgCredentials({});
    const next = presets.data?.find((option) => option.id === id);
    if (!next) return;
    if (!name.trim()) setName(next.name);
    const first = next.auth_methods.find((method) => method !== null);
    setSignIn({
      ...DEFAULT_SIGN_IN,
      authMode: first ? "individual" : "none",
      authMethod: first ?? null,
      providerMode: "preset",
    });
  }

  function config(current: IntegrationShape): IntegrationConfig | null {
    switch (current) {
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

  async function submit(current: IntegrationShape) {
    const body = config(current);
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
      onCreated(created);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("createFailed"));
    } finally {
      setBusy(false);
    }
  }

  if (step.kind === "openapiSchema")
    return (
      <Modal open onOpenChange={(open) => !open && close()}>
        <PluginModalContent>
          <AddOpenAPIActionModal
            title={t("openapi.title")}
            initialDefinition={openapiSpec ?? undefined}
            initialDescription={description}
            onBusyChange={setBusy}
            onClose={close}
            onConfigureAuthentication={(draft) => {
              setOpenapiSpec(draft.definition);
              setName(draft.name);
              setDescription(draft.description);
              setStep({ kind: "form", shape: "openapi" });
            }}
          />
        </PluginModalContent>
      </Modal>
    );

  return (
    <Modal open onOpenChange={(open) => !open && close()}>
      <PluginModalContent>
        <Modal.Header
          icon={shape ? SHAPE_ICONS[shape] : undefined}
          title={shape ? t(`formTitle.${shape}`) : t("title")}
          description={shape ? undefined : t("description")}
          onClose={close}
        />
        <Modal.Body padding={4} gap={4} alignItems="stretch">
          {step.kind === "pick" ? (
            <Section gap={2} alignItems="stretch" height="auto">
              {shapes.map((option) => (
                <SelectCard
                  key={option}
                  padding={3}
                  role="button"
                  tabIndex={0}
                  aria-label={kindCopy(option)}
                  onClick={() =>
                    setStep(
                      option === "openapi"
                        ? { kind: "openapiSchema" }
                        : { kind: "form", shape: option }
                    )
                  }
                >
                  <Content
                    icon={SHAPE_ICONS[option]}
                    title={kindCopy(option)}
                    description={t(`kindDescription.${option}`)}
                  />
                </SelectCard>
              ))}
            </Section>
          ) : (
            <>
              {step.shape === "preset" &&
                (presets.isLoading ? (
                  <IconLoader />
                ) : presets.error ? (
                  <MessageCard variant="error" title={t("preset.loadFailed")} />
                ) : (
                  <InputVertical
                    title={t("preset.title")}
                    error={
                      showErrors && !preset ? t("preset.required") : undefined
                    }
                  >
                    <InputSingleSelect
                      placeholder={t("preset.placeholder")}
                      value={presetId}
                      disabled={busy}
                      options={(presets.data ?? []).map((option) => ({
                        value: option.id,
                        title: option.name,
                      }))}
                      onValueChange={pickPreset}
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
              {step.shape === "mcp_server" && (
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
              {step.shape === "custom" && (
                <InputVertical
                  title={t("custom.patterns.title")}
                  description={t("custom.patterns.description")}
                  error={
                    showErrors && !config("custom")
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
              {(step.shape !== "preset" || preset) && (
                <IntegrationSignInFields
                  draft={signIn}
                  onChange={changeSignIn}
                  methods={methods}
                  preset={step.shape === "preset"}
                  showErrors={showErrors}
                  disabled={busy}
                />
              )}
              {canChooseOrganization && (
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
                      { value: "organization", title: t("owner.organization") },
                    ]}
                    onValueChange={(value) =>
                      setForOrganization(value === "organization")
                    }
                  />
                </InputVertical>
              )}
              {!canChooseOrganization && (
                <Text font="secondary-body" color="text-03">
                  {t("owner.personalDescription")}
                </Text>
              )}
            </>
          )}
        </Modal.Body>
        {step.kind === "form" && (
          <Modal.Footer>
            <BasicModalFooter
              cancel={
                <Button
                  prominence="secondary"
                  disabled={busy}
                  onClick={() => {
                    setShowErrors(false);
                    setStep(
                      step.shape === "openapi"
                        ? { kind: "openapiSchema" }
                        : { kind: "pick" }
                    );
                  }}
                >
                  {t("back")}
                </Button>
              }
              submit={
                <Button disabled={busy} onClick={() => void submit(step.shape)}>
                  {busy ? t("adding") : t("submit")}
                </Button>
              }
            />
          </Modal.Footer>
        )}
      </PluginModalContent>
    </Modal>
  );
}
