"use client";
import { useEffect, useRef, useState } from "react";
import { Formik } from "formik";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import {
  Button,
  Divider,
  InputTypeIn,
  LinkButton,
  MessageCard,
  Modal,
  Text,
} from "@opal/components";
import { InputVertical, Section } from "@opal/layouts";
import { SvgCheck, SvgX } from "@opal/icons";
import { IconLoader } from "@opal/loaders";
import { cn } from "@opal/utils";
import type { RichStr } from "@opal/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useDefaultAssistantConfiguration } from "@/lib/agents/hooks";
import { refreshMemberPluginCaches } from "@/lib/plugins/member";
import { useUser } from "@/providers/UserProvider";
import { consumeMcpChatEnableIntent } from "@/sections/actions/mcpChatEnableIntent";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import { useSettings } from "@/lib/settings/hooks";
import { useTierAtLeast } from "@/lib/tiers/hooks";
import { Tier } from "@/lib/tiers/types";
import { useUserGroups } from "@/lib/hooks";
import {
  createMCPServer,
  streamMCPServerProbe,
  refreshMCPServerTools,
  updateMCPServer,
  updateMCPServerStatus,
} from "@/lib/mcp/svc";
import {
  MCPServerStatus,
  MCPTransportType,
  type MCPServer,
  type MCPServerCreateRequest,
  type MCPServerConfigurationValues,
  type MCPSetupProbeResult,
  type MCPSetupRecommendation,
  type MCPProbeProgress,
} from "@/lib/mcp/types";
import MCPAuthenticationPage from "@/sections/actions/modals/MCPAuthenticationPage";
import PluginAvailabilitySwitch from "@/sections/plugins/PluginAvailabilitySwitch";
import PluginModalContent from "@/sections/plugins/PluginModalContent";
import {
  MCPAccessControl,
  validateMCPAccess,
} from "@/sections/actions/modals/MCPServerDetailsPage";
import MCPFormActions from "@/sections/actions/modals/MCPFormActions";
import styles from "@/sections/actions/modals/MCPPluginSetupModal.module.css";

interface ProbeStages {
  contacting_server?: MCPProbeProgress["state"];
  authentication?: MCPProbeProgress["state"];
}
type ProbeState =
  | { kind: "idle" }
  | { kind: "checking"; url: string }
  | {
      kind: "checked";
      url: string;
      result: MCPSetupProbeResult;
      progress: ProbeStages;
    };

function endpoint(value: string): string | null {
  try {
    const url = new URL(value.trim());
    return url.protocol === "https:" || url.protocol === "http:"
      ? url.href
      : null;
  } catch {
    return null;
  }
}

interface MCPPluginSetupModalProps {
  open: boolean;
  onClose: () => void;
  onCompleted: (server: MCPServer) => void;
  initialUrl?: string;
  initialName?: string;
  setupGuide?: {
    url: string;
    description: string | RichStr;
    note?: string | RichStr;
  };
}

export default function MCPPluginSetupModal({
  open,
  ...sessionProps
}: MCPPluginSetupModalProps) {
  return open ? <MCPSetupSession {...sessionProps} /> : null;
}

function MCPSetupSession({
  onClose,
  onCompleted,
  initialUrl = "",
  initialName = "",
  setupGuide,
}: Omit<MCPPluginSetupModalProps, "open">) {
  const t = useTranslations("actions");
  const { mutate } = useSWRConfig();
  const defaultChat = useDefaultAssistantConfiguration();
  const [enableChat, setEnableChat] = useState(true);
  const { user, userResolution } = useUser();
  const actor = useRef(user?.id);
  useEffect(() => {
    actor.current = user?.id;
  }, [user?.id]);
  const { isGlobalHolder, isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_ACTIONS
  );
  const settings = useSettings();
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const canRestrict = businessTier && settings.enterprise !== null;
  const { isLoading: groupsLoading, error: groupsError } =
    useUserGroups(canRestrict);
  const authorityLoading = userResolution !== "resolved" || settings.isLoading;
  const authorized = isGlobalHolder || isScopedManager;
  const [url, setUrl] = useState(initialUrl);
  const [touched, setTouched] = useState(false);
  const [step, setStep] = useState<"server" | "connection">("server");
  const [probe, setProbe] = useState<ProbeState>({ kind: "idle" });
  const [progress, setProgress] = useState<ProbeStages>({});
  const [retry, setRetry] = useState(0);
  const [connection, setConnection] = useState<{
    name: string;
    url: string;
    recommendation: MCPSetupRecommendation;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const savedServer = useRef<MCPServer | null>(null);
  const closeRequested = useRef(false);
  const lastProbe = useRef<Extract<ProbeState, { kind: "checked" }> | null>(
    null
  );
  const urlInput = useRef<HTMLInputElement>(null);
  const connectionPanel = useRef<HTMLDivElement>(null);
  const [footerTarget, setFooterTarget] = useState<HTMLDivElement | null>(null);
  const normalizedUrl = endpoint(url);
  const leave = () => {
    if (busy || closeRequested.current) return;
    closeRequested.current = true;
    onClose();
  };

  useEffect(() => {
    if (!normalizedUrl || !authorized || authorityLoading || step !== "server")
      return;
    if (lastProbe.current?.url === normalizedUrl && retry === 0) {
      setProbe(lastProbe.current);
      setProgress(lastProbe.current.progress);
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      let stages: ProbeStages = { contacting_server: "pending" };
      setProbe({ kind: "checking", url: normalizedUrl });
      setProgress({ contacting_server: "pending" });
      let result: MCPSetupProbeResult;
      try {
        result = await streamMCPServerProbe(
          normalizedUrl,
          (event) => {
            stages = { ...stages, [event.stage]: event.state };
            if (!cancelled) setProgress(stages);
          },
          controller.signal
        );
      } catch {
        result = { kind: "unreachable", reason: "connection_failed" };
        stages = {
          ...stages,
          [stages.contacting_server === "success"
            ? "authentication"
            : "contacting_server"]: "error",
        };
        if (!cancelled) setProgress(stages);
      }
      if (!cancelled) {
        lastProbe.current = {
          kind: "checked",
          url: normalizedUrl,
          result,
          progress: stages,
        };
        setProbe(lastProbe.current);
        setRetry(0);
      }
    }, 700);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [normalizedUrl, authorized, authorityLoading, step, retry]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      if (step === "server") urlInput.current?.focus();
      else if (
        step === "connection" &&
        !connectionPanel.current?.contains(document.activeElement)
      )
        connectionPanel.current
          ?.querySelector<HTMLElement>('[role="combobox"]')
          ?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [step, authorityLoading]);

  const checked =
    probe.kind === "checked" && probe.url === normalizedUrl
      ? probe.result
      : null;
  const initialValues: MCPServerConfigurationValues = {
    name: initialName,
    description: "",
    server_url: "",
    is_public: isGlobalHolder && !isScopedManager,
    access_mode: isScopedManager ? "groups" : "public",
    groups: [],
    users: [],
    available_in_craft: settings.onyx_craft_available === true,
  };

  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (open || busy) return;
        leave();
      }}
    >
      <PluginModalContent>
        <div className="contents">
          <Modal.Header
            padding={4}
            title={
              step === "connection" && connection
                ? t("mcpSetup.connectTo", { name: connection.name })
                : t("addMcpModal.addHeader.title")
            }
            onClose={leave}
          />
          <Modal.Body twoTone={false} padding={0} gap={0} alignItems="stretch">
            {authorityLoading ? (
              <Section padding={6}>
                <IconLoader />
              </Section>
            ) : !authorized ? (
              <Section padding={6}>
                <MessageCard
                  variant="error"
                  title={t("mcpSetup.permissionDenied")}
                />
              </Section>
            ) : (
              <Formik<MCPServerConfigurationValues>
                initialValues={initialValues}
                validateOnMount
                validate={(values) => {
                  const errors = validateMCPAccess(
                    values,
                    isScopedManager,
                    t("addMcpModal.access.groups.required")
                  );
                  if (!values.name.trim())
                    errors.name = t("addMcpModal.name.required");
                  return errors;
                }}
                onSubmit={() => undefined}
              >
                {(details) => {
                  const accessReady =
                    Object.keys(
                      validateMCPAccess(
                        details.values,
                        isScopedManager,
                        t("addMcpModal.access.groups.required")
                      )
                    ).length === 0 &&
                    (details.values.is_public || canRestrict) &&
                    !(
                      details.values.access_mode === "groups" &&
                      (groupsLoading || groupsError)
                    );
                  const continueToConnection = (
                    recommendation: MCPSetupRecommendation
                  ) => {
                    if (!normalizedUrl || !accessReady) return;
                    const name =
                      details.values.name.trim() ||
                      initialName.trim() ||
                      (recommendation.kind === "public" &&
                      recommendation.server_name.trim()
                        ? recommendation.server_name
                        : new URL(normalizedUrl).hostname);
                    if (!details.values.name.trim())
                      void details.setFieldValue("name", name);
                    setConnection({ url: normalizedUrl, recommendation, name });
                    setStep("connection");
                  };
                  const resolveServer = async () => {
                    const errors = await details.validateForm();
                    if (
                      Object.keys(errors).length ||
                      (!details.values.is_public && !canRestrict) ||
                      (details.values.access_mode === "groups" &&
                        (groupsLoading || groupsError))
                    ) {
                      await details.setTouched({ name: true, groups: true });
                      throw new Error(t("mcpSetup.reviewSettings"));
                    }
                    if (!connection)
                      throw new Error(t("mcpSetup.reviewSettings"));
                    const payload: MCPServerCreateRequest = {
                      name: details.values.name.trim(),
                      description: details.values.description,
                      server_url: connection.url,
                      is_public: details.values.is_public,
                      available_in_craft: details.values.available_in_craft,
                      groups: details.values.is_public
                        ? []
                        : details.values.groups,
                      users: details.values.is_public
                        ? []
                        : details.values.users,
                    };
                    const server = savedServer.current
                      ? await updateMCPServer(savedServer.current.id, payload)
                      : await createMCPServer(payload);
                    savedServer.current = server;
                    details.resetForm({ values: details.values });
                    return server;
                  };
                  return (
                    <>
                      <div
                        hidden={step !== "server"}
                        className={connection ? styles.panel : undefined}
                        data-direction="back"
                      >
                        <Section
                          alignItems="stretch"
                          padding={6}
                          gap={4}
                          height="auto"
                        >
                          <InputVertical
                            withLabel="mcp-setup-initial-name"
                            title={t("addMcpModal.name.title")}
                          >
                            <InputTypeIn
                              id="mcp-setup-initial-name"
                              name="name"
                              value={details.values.name}
                              onChange={details.handleChange}
                              placeholder={t("addMcpModal.name.title")}
                            />
                          </InputVertical>
                          <InputVertical
                            withLabel="mcp-setup-url"
                            title={t("addMcpModal.serverUrl.title")}
                            description={t("mcpSetup.urlDescription")}
                          >
                            <InputTypeIn
                              id="mcp-setup-url"
                              name="server_url"
                              type="url"
                              ref={urlInput}
                              value={url}
                              placeholder={t("placeholders.mcpServerUrl")}
                              variant={
                                touched && url && !normalizedUrl
                                  ? "error"
                                  : "primary"
                              }
                              onBlur={() => setTouched(true)}
                              onChange={(event) => {
                                const nextUrl = endpoint(event.target.value);
                                setUrl(event.target.value);
                                if (nextUrl !== normalizedUrl) {
                                  setRetry(0);
                                  setProbe({ kind: "idle" });
                                  setProgress({});
                                }
                                if (nextUrl !== connection?.url)
                                  setConnection(null);
                              }}
                            />
                            {touched && url && !normalizedUrl && (
                              <Text
                                font="secondary-body"
                                color="status-error-05"
                              >
                                {t("addMcpModal.serverUrl.invalid")}
                              </Text>
                            )}
                          </InputVertical>
                          {setupGuide && (
                            <div className="flex flex-col items-start gap-2">
                              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                                <Text font="secondary-body" color="text-03">
                                  {setupGuide.description}
                                </Text>
                                <LinkButton
                                  href={setupGuide.url}
                                  target="_blank"
                                >
                                  {t("plugins.catalog.setupGuide")}
                                </LinkButton>
                              </div>
                              {setupGuide.note && (
                                <Text font="secondary-body" color="text-03">
                                  {setupGuide.note}
                                </Text>
                              )}
                            </div>
                          )}
                          <div
                            role={
                              checked?.kind === "unreachable"
                                ? "alert"
                                : "status"
                            }
                            className="flex flex-col gap-3"
                          >
                            {(
                              ["authentication", "contacting_server"] as const
                            ).map((stage) => {
                              let state =
                                checked?.kind === "oauth" ||
                                checked?.kind === "public"
                                  ? "success"
                                  : (progress[stage] ?? "pending");
                              if (
                                checked?.kind === "unreachable" &&
                                state === "pending"
                              ) {
                                state = "error";
                              }
                              return (
                                <div
                                  key={stage}
                                  className={cn(
                                    "grid grid-cols-[1rem_minmax(0,1fr)_auto] items-center gap-3",
                                    styles.stage
                                  )}
                                  data-stage={stage}
                                  data-state={state}
                                >
                                  <span
                                    aria-hidden="true"
                                    className={styles.statusIcon}
                                  >
                                    <span data-icon="pending">
                                      <IconLoader size={16} />
                                    </span>
                                    <span data-icon="success">
                                      <SvgCheck className="size-4 text-status-success-05" />
                                    </span>
                                    <span data-icon="error">
                                      <SvgX className="size-4 text-status-error-05" />
                                    </span>
                                  </span>
                                  <Text font="secondary-body" color="text-04">
                                    {t(
                                      stage === "authentication"
                                        ? "mcpAuthModal.authType.label"
                                        : "mcpAuthModal.transport.label"
                                    )}
                                  </Text>
                                  <Text font="secondary-body" color="text-03">
                                    {checked && checked.kind !== "unreachable"
                                      ? stage === "authentication"
                                        ? t(
                                            checked.kind === "oauth"
                                              ? "mcpSetup.oauthDetected"
                                              : checked.kind === "public"
                                                ? "mcpSetup.publicDetected"
                                                : "mcpSetup.manualRequired"
                                          )
                                        : t(
                                            checked.transport ===
                                              MCPTransportType.SSE
                                              ? "mcpAuthModal.transport.sseLabel"
                                              : "mcpAuthModal.transport.httpLabel"
                                          )
                                      : t(
                                          state === "pending"
                                            ? "mcpSetup.stagePending"
                                            : state === "success"
                                              ? "mcpSetup.stageSuccess"
                                              : "mcpSetup.stageError"
                                        )}
                                  </Text>
                                </div>
                              );
                            })}
                            {checked?.kind === "unreachable" && (
                              <Text font="secondary-body" color="text-03">
                                {t("mcpSetup.unreachable")}
                              </Text>
                            )}
                            {checked?.kind === "unreachable" && (
                              <Text font="secondary-body" color="text-03">
                                {t(
                                  checked.reason === "blocked"
                                    ? "mcpSetup.blocked"
                                    : "mcpSetup.retryCheck"
                                )}
                              </Text>
                            )}
                            {checked?.kind === "unreachable" && (
                              <div className="flex flex-wrap gap-3">
                                <Button
                                  prominence="secondary"
                                  onClick={() => setRetry((value) => value + 1)}
                                >
                                  {t("mcpSetup.retry")}
                                </Button>
                                {checked.reason === "connection_failed" && (
                                  <Button
                                    prominence="tertiary"
                                    disabled={!accessReady}
                                    onClick={() =>
                                      continueToConnection({
                                        kind: "auth_unknown",
                                        transport: null,
                                      })
                                    }
                                  >
                                    {t("mcpSetup.configureManually")}
                                  </Button>
                                )}
                              </div>
                            )}
                          </div>
                          <Divider paddingParallel={0} />
                          <MCPAccessControl
                            isGlobalHolder={isGlobalHolder}
                            isScopedManager={isScopedManager}
                            canRestrict={canRestrict}
                            disabled={busy}
                          />
                          {defaultChat.canEdit && (
                            <PluginAvailabilitySwitch
                              surface="chat"
                              enabled={enableChat}
                              disabled={busy}
                              onChange={setEnableChat}
                            />
                          )}
                          {settings.onyx_craft_available === true && (
                            <PluginAvailabilitySwitch
                              surface="mcp-craft"
                              enabled={
                                details.values.available_in_craft === true
                              }
                              disabled={busy}
                              onChange={(enabled) =>
                                void details.setFieldValue(
                                  "available_in_craft",
                                  enabled
                                )
                              }
                            />
                          )}
                          <MCPFormActions
                            variant="modal"
                            active={step === "server"}
                            footerTarget={footerTarget}
                            cancel={
                              <Button prominence="secondary" onClick={leave}>
                                {t("addMcpModal.cancelButton.label")}
                              </Button>
                            }
                            submit={
                              <Button
                                disabled={
                                  !checked ||
                                  checked.kind === "unreachable" ||
                                  !accessReady
                                }
                                onClick={() => {
                                  if (checked && checked.kind !== "unreachable")
                                    continueToConnection(checked);
                                }}
                              >
                                {t("mcpSetup.continue")}
                              </Button>
                            }
                          />
                        </Section>
                      </div>
                      {connection && (
                        <div
                          hidden={step === "server"}
                          ref={connectionPanel}
                          className={styles.panel}
                          data-direction="forward"
                        >
                          <MCPAuthenticationPage
                            key={connection.url}
                            variant="modal"
                            footerTarget={footerTarget}
                            active={step !== "server"}
                            mcpServer={{
                              name: details.values.name,
                              description: details.values.description,
                              server_url: connection.url,
                            }}
                            resolveServer={resolveServer}
                            enableChatOnConnect={
                              defaultChat.canEdit && enableChat
                            }
                            recommendation={connection.recommendation}
                            canSubmit={
                              details.isValid &&
                              accessReady &&
                              !(defaultChat.canEdit && defaultChat.isLoading)
                            }
                            onBusyChange={setBusy}
                            onBack={() => setStep("server")}
                            onCancel={leave}
                            onSaved={async () => {
                              await mutate(SWR_KEYS.adminMcpServers);
                            }}
                            onTriggerFetchTools={async (id, token) => {
                              await updateMCPServerStatus(
                                id,
                                MCPServerStatus.FETCHING_TOOLS
                              );
                              const tools = await refreshMCPServerTools(id);
                              await mutate(
                                SWR_KEYS.adminMcpServerToolSnapshots(id),
                                tools,
                                { revalidate: false }
                              );
                              if (
                                defaultChat.canEdit &&
                                tools.length > 0 &&
                                consumeMcpChatEnableIntent(token, {
                                  userId: actor.current,
                                  serverId: id,
                                })
                              ) {
                                if (!defaultChat.data || defaultChat.error)
                                  throw new Error(
                                    t("addMcpModal.toasts.updateFailed")
                                  );
                                await defaultChat.updateTools(
                                  tools.map((tool) => tool.id),
                                  true
                                );
                              }
                              await refreshMemberPluginCaches(mutate);
                            }}
                            onComplete={() => {
                              if (!savedServer.current) return;
                              onCompleted(savedServer.current);
                            }}
                          />
                        </div>
                      )}
                    </>
                  );
                }}
              </Formik>
            )}
          </Modal.Body>
          <div ref={setFooterTarget} className="shrink-0" />
        </div>
      </PluginModalContent>
    </Modal>
  );
}
