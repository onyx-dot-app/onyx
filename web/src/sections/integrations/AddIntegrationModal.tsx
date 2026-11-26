"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import {
  BasicModalFooter,
  Button,
  Card,
  Collapsible,
  FilePickerButton,
  InputSingleSelect,
  InputTypeIn,
  MessageCard,
  Modal,
  SelectCard,
  Text,
} from "@opal/components";
import {
  CardGrid,
  Content,
  InputErrorText,
  InputVertical,
  Section,
  toast,
} from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { SvgPlug, SvgUploadCloud, SvgX } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { useNavigation } from "@opal/navigation";
import { getAppTypeLogo } from "@/app/craft/v1/apps/registry";
import {
  integrationHref,
  type NewIntegrationPrefill,
} from "@/lib/customize/paths";
import { FetchError } from "@/lib/fetcher";
import { appType } from "@/lib/integrations/craft";
import { useIntegrationPresets } from "@/lib/integrations/hooks";
import { createIntegration } from "@/lib/integrations/svc";
import type {
  AuthMethod,
  EndpointLineError,
  IntegrationConfig,
  IntegrationPreset,
  IntegrationShape,
  McpTransport,
} from "@/lib/integrations/types";
import { integrationDetailHref } from "@/lib/integrations/utils";
import { streamMCPServerProbe } from "@/lib/mcp/svc";
import type { MCPSetupProbeResult } from "@/lib/mcp/types";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import {
  hasSuggestedMcpServer,
  SUGGESTED_MCP_PLUGINS,
} from "@/lib/plugins/catalog";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Permission } from "@/lib/types";
import CredentialFieldInputs from "@/sections/integrations/CredentialFieldInputs";
import {
  detectApi,
  isNotThisKind,
  restBaseUrl,
  SPEC_MAX_SIZE_KB,
  type DetectedApi,
  type SpecFile,
} from "@/sections/integrations/detectApi";
import {
  INTEGRATION_SHAPE_ICONS,
  useIntegrationLabels,
} from "@/sections/integrations/integrationLabels";
import {
  SignInMethodFields,
  SignInModeField,
} from "@/sections/integrations/IntegrationSignInFields";
import PresetSetupPanel from "@/sections/integrations/PresetSetupPanel";
import {
  EndpointLinesField,
  SkippedOperations,
} from "@/sections/integrations/RestEndpointFields";
import {
  DEFAULT_SIGN_IN,
  normalizedUrl,
  presetAuthMethods,
  SIGN_IN_METHODS,
  signInErrors,
  signInPayload,
  type SignInDraft,
} from "@/sections/integrations/signIn";

export type AddIntegrationStart =
  | { kind: "mcp_server" }
  | { kind: "api" }
  | { kind: "catalog" }
  | { kind: "prefill"; prefill: NewIntegrationPrefill };

type Flow = "mcp_server" | "api" | "catalog";
type Step = "catalog" | "connect" | "detecting" | "setup";
type McpProbe = MCPSetupProbeResult | { kind: "forbidden" };
type Detection =
  | { shape: "mcp_server"; probe: McpProbe }
  | { shape: "preset"; preset: IntegrationPreset }
  | DetectedApi;

/** The URL and spec file that a detection checked. */
interface DetectionInputs {
  url: string | null;
  file: SpecFile | null;
}

const TRANSPORTS: readonly McpTransport[] = ["STREAMABLE_HTTP", "SSE"];

/** Sign-in from the probe. The method is set even with no sign-in, so a
 * later choice of sign-in starts from a working method. */
function mcpSignIn(probe: McpProbe): SignInDraft {
  switch (probe.kind) {
    case "oauth":
      return {
        ...DEFAULT_SIGN_IN,
        authMode: "individual",
        authMethod: "oauth2",
        providerMode: probe.discovery.supports_automatic_registration
          ? "discovery"
          : "manual",
        authorizationUrl: probe.discovery.authorization_endpoint ?? "",
        tokenUrl: probe.discovery.token_endpoint ?? "",
      };
    case "auth_unknown":
      return {
        ...DEFAULT_SIGN_IN,
        authMode: "individual",
        authMethod: "api_key",
      };
    default:
      return {
        ...DEFAULT_SIGN_IN,
        authMethod: "oauth2",
        providerMode: "discovery",
      };
  }
}

function presetSignIn(preset: IntegrationPreset): SignInDraft {
  const first = presetAuthMethods(preset)[0];
  return {
    ...DEFAULT_SIGN_IN,
    authMode: first ? "individual" : "none",
    authMethod: first ?? null,
    providerMode: "preset",
  };
}

function presetLogo(preset: IntegrationPreset): IconFunctionComponent {
  return getAppTypeLogo(appType(preset.id));
}

interface AddIntegrationModalProps {
  /** Admin adds to either library; Customize adds to the user's own. */
  from: "admin" | "customize";
  start: AddIntegrationStart;
  onClose: () => void;
}

/** Adds an integration in two steps: a name and a URL, then the sign-in
 * that Onyx detected. The detail page holds the rest. */
export default function AddIntegrationModal({
  from,
  start,
  onClose,
}: AddIntegrationModalProps) {
  const t = useTranslations("admin.integrations.add");
  const labels = useIntegrationLabels();
  const locale = useLocale();
  const navigation = useNavigation();
  const { mutate } = useSWRConfig();
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_ACTIONS);
  const canChooseOrganization = from === "admin" && isGlobalHolder;
  const prefill = start.kind === "prefill" ? start.prefill : null;
  const flow: Flow = start.kind === "prefill" ? "mcp_server" : start.kind;
  const presets = useIntegrationPresets(flow === "catalog");

  // A link with a bad URL opens the form with the URL error.
  const badPrefillUrl = prefill !== null && !normalizedUrl(prefill.serverUrl);
  const [step, setStep] = useState<Step>(
    flow === "catalog"
      ? "catalog"
      : prefill && !badPrefillUrl
        ? "detecting"
        : "connect"
  );
  const [name, setName] = useState(prefill?.name ?? "");
  const [url, setUrl] = useState(prefill?.serverUrl ?? "");
  const [file, setFile] = useState<SpecFile | null>(null);
  const [readingFile, setReadingFile] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [detectError, setDetectError] = useState<string | null>(null);
  const [detection, setDetection] = useState<Detection | null>(null);
  const [signIn, setSignIn] = useState<SignInDraft>(DEFAULT_SIGN_IN);
  const [transport, setTransport] = useState<McpTransport>(
    prefill?.transport ?? "STREAMABLE_HTTP"
  );
  const [endpoints, setEndpoints] = useState("");
  // The base URL of a spec with no single server URL.
  const [baseUrl, setBaseUrl] = useState("");
  const [lineErrors, setLineErrors] = useState<EndpointLineError[]>([]);
  const [orgCredentials, setOrgCredentials] = useState<Record<string, string>>(
    {}
  );
  // Null until the user picks: the prefill decides.
  const [ownerChoice, setOwnerChoice] = useState<boolean | null>(null);
  const forOrganization = ownerChoice ?? prefill?.forOrganization === true;
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [showErrors, setShowErrors] = useState(badPrefillUrl);
  const [busy, setBusy] = useState(false);
  // Each detection gets a new run; Back and close drop the run in flight.
  const run = useRef<AbortController | null>(null);
  // Continue with these inputs again returns to the setup step as it was.
  const detectedFrom = useRef<DetectionInputs | null>(null);

  useEffect(() => {
    if (prefill && !badPrefillUrl) {
      void probeMcp(prefill.name, prefill.serverUrl);
    }
    return () => run.current?.abort();
    // Runs once: the prefill is where this modal starts.
  }, []);

  const shape: Exclude<IntegrationShape, "custom"> =
    detection === null
      ? "mcp_server"
      : detection.shape === "rest"
        ? "openapi"
        : detection.shape;
  const methods: readonly AuthMethod[] =
    shape !== "preset"
      ? SIGN_IN_METHODS[shape]
      : detection?.shape === "preset"
        ? presetAuthMethods(detection.preset)
        : [];

  function newRun(): AbortController {
    run.current?.abort();
    run.current = new AbortController();
    return run.current;
  }

  function enterSetup(
    next: Detection,
    signInDraft: SignInDraft,
    inputs: DetectionInputs | null
  ) {
    detectedFrom.current = inputs;
    setDetection(next);
    setSignIn(signInDraft);
    setShowErrors(false);
    setLineErrors([]);
    setStep("setup");
  }

  async function probeMcp(nextName: string, serverUrl: string) {
    const controller = newRun();
    setName(nextName);
    setUrl(serverUrl);
    setStep("detecting");
    let probe: McpProbe;
    try {
      probe = await streamMCPServerProbe(
        serverUrl,
        () => undefined,
        controller.signal
      );
    } catch (failure) {
      if (controller.signal.aborted) return;
      // Only admins can check a server. The add still works.
      probe =
        failure instanceof FetchError && failure.status === 403
          ? { kind: "forbidden" }
          : { kind: "unreachable", reason: "connection_failed" };
    }
    if (controller.signal.aborted) return;
    // A probe with no transport falls back to the default, not to the
    // transport of the server before Back.
    const found =
      probe.kind !== "unreachable" && probe.kind !== "forbidden"
        ? probe.transport
        : null;
    setTransport(
      found ??
        (prefill &&
        normalizedUrl(serverUrl) === normalizedUrl(prefill.serverUrl)
          ? prefill.transport
          : "STREAMABLE_HTTP")
    );
    enterSetup({ shape: "mcp_server", probe }, mcpSignIn(probe), {
      url: normalizedUrl(serverUrl),
      file: null,
    });
  }

  async function detectCustomApi(apiUrl: string | null) {
    const controller = newRun();
    setStep("detecting");
    let detected: DetectedApi | null;
    try {
      detected = await detectApi(apiUrl, file);
    } catch (error) {
      if (controller.signal.aborted) return;
      setDetectError(
        isNotThisKind(error)
          ? t("api.specError", { detail: error.message })
          : t("api.checkFailed")
      );
      setStep("connect");
      return;
    }
    if (controller.signal.aborted) return;
    if (!detected) {
      setDetectError(t("api.url.needed"));
      setStep("connect");
      return;
    }
    if (detected.shape === "openapi") setBaseUrl(detected.view.base_url);
    setEndpoints("");
    // Most APIs take a key; the method is ready for a later choice of sign-in.
    enterSetup(
      detected,
      { ...DEFAULT_SIGN_IN, authMethod: "api_key" },
      { url: apiUrl, file }
    );
  }

  function pickPreset(preset: IntegrationPreset) {
    setName(preset.name);
    setOrgCredentials({});
    enterSetup({ shape: "preset", preset }, presetSignIn(preset), null);
  }

  function next() {
    setShowErrors(true);
    setDetectError(null);
    if (!name.trim()) return;
    const target = normalizedUrl(url);
    const last = detectedFrom.current;
    if (last && last.url === target && last.file === file) {
      setShowErrors(false);
      setStep("setup");
      return;
    }
    if (flow === "mcp_server") {
      if (target) void probeMcp(name, target);
      return;
    }
    if (url.trim() ? !target : !file) return;
    void detectCustomApi(target);
  }

  function back() {
    run.current?.abort();
    setStep(flow === "catalog" ? "catalog" : "connect");
  }

  function config(): IntegrationConfig | null {
    switch (detection?.shape) {
      case undefined:
        return null;
      case "mcp_server": {
        const serverUrl = normalizedUrl(url);
        return serverUrl
          ? { shape: "mcp_server", server_url: serverUrl, transport }
          : null;
      }
      case "openapi": {
        const base = restBaseUrl(baseUrl);
        if (!base) return null;
        return {
          shape: "openapi",
          openapi_document: detection.view.openapi_document,
          base_url: base,
          endpoints: detection.view.endpoints,
        };
      }
      case "rest": {
        const lines = endpoints.split("\n");
        if (!lines.some((line) => line.trim())) return null;
        return {
          shape: "openapi",
          openapi_document: null,
          base_url: detection.baseUrl,
          endpoints: lines,
        };
      }
      case "graphql":
        return detection.config;
      case "preset": {
        const { preset } = detection;
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
    }
  }

  async function add() {
    const body = config();
    const errors = signInErrors(signIn);
    if (!body || errors.length > 0) {
      setShowErrors(true);
      if (errors.length > 0) setAdvancedOpen(true);
      return;
    }
    setBusy(true);
    setLineErrors([]);
    try {
      const created = await createIntegration({
        for_organization: canChooseOrganization && forOrganization,
        name: name.trim(),
        description: null,
        ...signInPayload(signIn),
        config: body,
      });
      toast.success(t("created", { name: created.name }));
      if (prefill?.returnTo) {
        await Promise.all([
          mutate(SWR_KEYS.integrations),
          mutate(SWR_KEYS.adminIntegrations),
        ]);
        navigation.go(prefill.returnTo);
        return;
      }
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
      if (error instanceof FetchError)
        setLineErrors(error.info?.line_errors ?? []);
      toast.error(error instanceof Error ? error.message : t("createFailed"));
      setBusy(false);
    }
  }

  function probeSummary(probe: McpProbe): string {
    switch (probe.kind) {
      case "public":
        return t("mcp.probe.public", { count: probe.tool_count });
      case "oauth":
        return t("mcp.probe.oauth");
      case "auth_unknown":
        return t("mcp.probe.authUnknown");
      case "unreachable":
        return t("mcp.probe.unreachable");
      case "forbidden":
        return t("mcp.probe.forbidden");
    }
  }

  function summary(found: Detection): string {
    switch (found.shape) {
      case "mcp_server":
        return probeSummary(found.probe);
      case "preset":
        return t("detected.preset");
      case "openapi":
        return found.view.skipped.length > 0
          ? t("detected.openapiSkipped", {
              count: found.view.endpoints.length,
              skipped: found.view.skipped.length,
            })
          : t("detected.openapi", { count: found.view.endpoints.length });
      case "rest":
        return t("detected.rest");
      case "graphql":
        return t("detected.graphql", {
          queries: found.queries,
          mutations: found.mutations,
        });
    }
  }

  const named = (flow === "catalog" || prefill) && step === "setup";
  const title = named
    ? t("modal.namedTitle", { name })
    : t(`modal.${flow}.title`);
  const showAdvanced =
    signIn.authMode !== "none" ||
    detection?.shape === "mcp_server" ||
    canChooseOrganization;

  function catalogStep() {
    if (presets.isLoading) return <IconLoader />;
    const tiles = [
      ...(presets.data ?? [])
        .filter((preset) => !hasSuggestedMcpServer(preset.id))
        .map((preset) => ({
          id: preset.id,
          name: preset.name,
          icon: presetLogo(preset),
          kind: labels.shape({ shape: "preset" }),
          onPick: () => pickPreset(preset),
        })),
      ...SUGGESTED_MCP_PLUGINS.map((server) => ({
        id: server.id,
        name: server.name,
        icon: server.icon,
        kind: labels.shape({ shape: "mcp_server" }),
        onPick: () => void probeMcp(server.name, server.serverUrl),
      })),
    ].sort((a, b) =>
      a.name.localeCompare(b.name, locale, { sensitivity: "base" })
    );
    return (
      <Section gap={4} alignItems="stretch" height="auto">
        {presets.error && (
          <MessageCard variant="error" title={t("preset.loadFailed")} />
        )}
        <CardGrid columns="one-to-four">
          {tiles.map((tile) => (
            <SelectCard
              key={tile.id}
              padding={2}
              role="button"
              aria-label={tile.name}
              tabIndex={0}
              state="empty"
              onClick={tile.onPick}
            >
              <Content
                icon={tile.icon}
                title={tile.name}
                titleMaxLines={1}
                description={tile.kind}
              />
            </SelectCard>
          ))}
        </CardGrid>
      </Section>
    );
  }

  function connectStep() {
    const apiUrl = normalizedUrl(url);
    const urlKey = flow === "mcp_server" ? "mcp.url" : "api.url";
    const urlError =
      flow === "mcp_server"
        ? showErrors && !apiUrl
          ? t("mcp.url.error")
          : undefined
        : (detectError ??
          (showErrors && (url.trim() ? !apiUrl : !file)
            ? t("api.url.error")
            : undefined));
    return (
      <Section gap={4} alignItems="stretch" height="auto">
        <InputVertical
          title={t("name.title")}
          error={showErrors && !name.trim() ? t("name.required") : undefined}
        >
          <InputTypeIn
            aria-label={t("name.title")}
            placeholder={t("name.placeholder")}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </InputVertical>
        <InputVertical
          title={t(`${urlKey}.title`)}
          description={
            flow === "mcp_server" ? undefined : t("api.url.description")
          }
          error={urlError}
        >
          <InputTypeIn
            aria-label={t(`${urlKey}.title`)}
            placeholder={t(`${urlKey}.placeholder`)}
            value={url}
            onChange={(event) => {
              setUrl(event.target.value);
              setDetectError(null);
            }}
          />
        </InputVertical>
        {flow === "api" && (
          <Section
            flexDirection="row"
            justifyContent="start"
            alignItems="center"
            gap={1}
            height="auto"
          >
            {file ? (
              <>
                <Text font="secondary-body" color="text-03">
                  {t("api.upload.chosen", { file: file.name })}
                </Text>
                <Button
                  size="sm"
                  prominence="tertiary"
                  icon={SvgX}
                  aria-label={t("api.upload.remove")}
                  onClick={() => {
                    setFile(null);
                    setDetectError(null);
                  }}
                />
              </>
            ) : (
              <FilePickerButton
                size="sm"
                prominence="tertiary"
                icon={SvgUploadCloud}
                multiple={false}
                inputLabel={t("api.upload.label")}
                onFiles={(files) => {
                  const picked = files[0];
                  if (!picked) return;
                  if (picked.size > SPEC_MAX_SIZE_KB * 1024) {
                    setFileError(t("api.tooLarge"));
                    return;
                  }
                  setReadingFile(true);
                  setFileError(null);
                  picked
                    .text()
                    .then((text) => {
                      setFile({ name: picked.name, text });
                      setDetectError(null);
                    })
                    .catch(() => setFileError(t("api.failed")))
                    .finally(() => setReadingFile(false));
                }}
              >
                {t("api.upload.label")}
              </FilePickerButton>
            )}
          </Section>
        )}
        {flow === "api" && fileError && (
          <InputErrorText type="error">{fileError}</InputErrorText>
        )}
      </Section>
    );
  }

  function setupStep(found: Detection) {
    return (
      <Section gap={4} alignItems="stretch" height="auto">
        <Card padding={2} border="solid">
          <Content
            icon={
              found.shape === "preset"
                ? presetLogo(found.preset)
                : INTEGRATION_SHAPE_ICONS[shape]
            }
            title={name}
            description={summary(found)}
          />
        </Card>
        {found.shape === "openapi" && (
          <SkippedOperations lines={found.view.skipped} />
        )}
        {found.shape === "openapi" && found.baseUrlGuessed && (
          <InputVertical
            title={t("rest.baseUrl.title")}
            error={
              showErrors && !restBaseUrl(baseUrl)
                ? t("rest.baseUrl.required")
                : undefined
            }
          >
            <InputTypeIn
              aria-label={t("rest.baseUrl.title")}
              placeholder={t("rest.baseUrl.placeholder")}
              value={baseUrl}
              variant={busy ? "disabled" : "primary"}
              onChange={(event) => setBaseUrl(event.target.value)}
            />
          </InputVertical>
        )}
        {found.shape === "preset" && (
          <CredentialFieldInputs
            fields={found.preset.required_org_credential_fields}
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
        <SignInModeField
          draft={signIn}
          onChange={setSignIn}
          methods={methods}
          shape={shape}
          showErrors={showErrors}
          disabled={busy}
        />
        {found.shape === "rest" && (
          <EndpointLinesField
            value={endpoints}
            onChange={(value) => {
              setEndpoints(value);
              setLineErrors([]);
            }}
            lineErrors={lineErrors}
            showErrors={showErrors}
            disabled={busy}
          />
        )}
        {showAdvanced && (
          <Collapsible
            title={t("advanced")}
            open={advancedOpen}
            onOpenChange={setAdvancedOpen}
          >
            <Section gap={4} alignItems="stretch" height="auto">
              <SignInMethodFields
                draft={signIn}
                onChange={setSignIn}
                methods={methods}
                shape={shape}
                showErrors={showErrors}
                disabled={busy}
              />
              {found.shape === "mcp_server" && (
                <InputVertical title={t("mcp.transport.title")}>
                  <InputSingleSelect
                    placeholder={t("mcp.transport.title")}
                    value={transport}
                    defaultOption="STREAMABLE_HTTP"
                    disabled={busy}
                    options={TRANSPORTS.map((value) => ({
                      value,
                      title:
                        value === "SSE"
                          ? t("mcp.transport.sse")
                          : t("mcp.transport.streamableHttp"),
                    }))}
                    onValueChange={(value) => {
                      const picked = TRANSPORTS.find(
                        (option) => option === value
                      );
                      if (picked) setTransport(picked);
                    }}
                  />
                </InputVertical>
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
                    defaultOption="personal"
                    disabled={busy}
                    options={[
                      { value: "personal", title: t("owner.personal") },
                      {
                        value: "organization",
                        title: t("owner.organization"),
                      },
                    ]}
                    onValueChange={(value) =>
                      setOwnerChoice(value === "organization")
                    }
                  />
                </InputVertical>
              )}
            </Section>
          </Collapsible>
        )}
      </Section>
    );
  }

  const backButton =
    step === "connect" ? (
      <Button prominence="secondary" onClick={onClose}>
        {t("cancel")}
      </Button>
    ) : (
      <Button prominence="secondary" disabled={busy} onClick={back}>
        {t("back")}
      </Button>
    );

  return (
    <Modal open onOpenChange={(open) => !open && !busy && onClose()}>
      <Modal.Content
        width={
          step === "catalog" ||
          (step === "setup" && detection?.shape === "preset")
            ? "lg"
            : "sm"
        }
        height="fit"
        maxHeight="80dvh"
      >
        <Modal.Header
          icon={SvgPlug}
          title={title}
          description={
            step !== "setup"
              ? t(`modal.${flow}.description`)
              : named || flow !== "mcp_server"
                ? labels.shape({ shape })
                : undefined
          }
          onClose={busy ? undefined : onClose}
        />
        <Modal.Body padding={4} gap={4} alignItems="stretch">
          {step === "catalog" && catalogStep()}
          {step === "connect" && connectStep()}
          {step === "detecting" && (
            <Section
              flexDirection="row"
              justifyContent="start"
              alignItems="center"
              gap={2}
              height="auto"
            >
              <IconLoader size={16} />
              <Text font="secondary-body" color="text-03">
                {t("detecting")}
              </Text>
            </Section>
          )}
          {step === "setup" &&
            detection &&
            (detection.shape === "preset" ? (
              // Narrow screens put the setup panel above the fields. Wide
              // screens pin it beside the fields, scrolling on its own; the
              // max height leaves room for the modal header and footer.
              <Section
                justifyContent="start"
                alignItems="stretch"
                gap={4}
                height="auto"
                className="md:flex-row-reverse md:items-start"
              >
                <Section
                  justifyContent="start"
                  alignItems="stretch"
                  height="auto"
                  className="md:w-80 md:shrink-0 md:sticky md:top-4 md:max-h-[calc(80dvh-16rem)] md:overflow-y-auto"
                >
                  <PresetSetupPanel preset={detection.preset} />
                </Section>
                <Section
                  alignItems="stretch"
                  height="auto"
                  className="md:min-w-0 md:flex-1"
                >
                  {setupStep(detection)}
                </Section>
              </Section>
            ) : (
              setupStep(detection)
            ))}
        </Modal.Body>
        {step !== "catalog" && (
          <Modal.Footer>
            <BasicModalFooter
              cancel={backButton}
              submit={
                step === "setup" ? (
                  <Button disabled={busy} onClick={() => void add()}>
                    {busy ? t("adding") : t("submit")}
                  </Button>
                ) : (
                  <Button
                    disabled={step === "detecting" || readingFile}
                    onClick={next}
                  >
                    {t("continue")}
                  </Button>
                )
              }
            />
          </Modal.Footer>
        )}
      </Modal.Content>
    </Modal>
  );
}
