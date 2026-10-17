"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  Button,
  InputTextArea,
  InputTypeIn,
  Modal,
  Tabs,
  Text,
} from "@opal/components";
import { Content, InputVertical, toast } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { SvgActions } from "@opal/icons";
import useOpenApiTools from "@/hooks/useOpenApiTools";
import { can } from "@/lib/permissions/resource-actions";
import { pluginDetailHref, withPluginSearchParams } from "@/lib/plugins/routes";
import { updateCustomTool } from "@/lib/tools/svc";
import {
  extractMethodSpecsFromDefinition,
  getActionIcon,
} from "@/lib/tools/utils";
import type { ToolSnapshot } from "@/lib/tools/types";
import AddOpenAPIActionModal from "@/sections/actions/modals/AddOpenAPIActionModal";
import OpenAPIAuthenticationModal, {
  type OpenAPIAuthFormValues,
} from "@/sections/actions/modals/OpenAPIAuthenticationModal";
import { saveOpenApiAuthentication } from "@/sections/plugins/openApiWorkflow";
import OpenAPIEndpointList from "@/sections/plugins/OpenAPIEndpointList";
import PluginModalContent from "@/sections/plugins/PluginModalContent";
import MCPFormActions from "@/sections/actions/modals/MCPFormActions";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";
import { UnsavedChangesModalContent } from "@/sections/modals/UnsavedChangesModal";

interface OpenAPIPluginDetailPageProps {
  toolId: number;
}

interface MetadataEditorProps {
  tool: ToolSnapshot;
  active: boolean;
  footerTarget: HTMLDivElement | null;
  onBusyChange: (busy: boolean) => void;
  onDirtyChange: (dirty: boolean) => void;
  onSave: (values: Pick<ToolSnapshot, "name" | "description">) => Promise<void>;
}

function MetadataEditor({
  tool,
  active,
  footerTarget,
  onBusyChange,
  onDirtyChange,
  onSave,
}: MetadataEditorProps) {
  const t = useTranslations("actions");
  const fields = useTranslations("agents.editor.general");
  const [draft, setDraft] = useState<Pick<
    ToolSnapshot,
    "name" | "description"
  > | null>(null);
  const name = draft?.name ?? tool.name;
  const description = draft?.description ?? tool.description;
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = name !== tool.name || description !== tool.description;
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);
  useEffect(() => {
    onBusyChange(pending);
    return () => onBusyChange(false);
  }, [pending, onBusyChange]);

  async function save() {
    setPending(true);
    setError(null);
    try {
      await onSave({ name: name.trim(), description: description.trim() });
      setDraft(null);
    } catch (cause) {
      setError(
        cause instanceof Error && cause.message
          ? cause.message
          : t("addOpenApiModal.toasts.updateFailed")
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <InputVertical title={fields("name.title")} withLabel="plugin-name">
        <InputTypeIn
          id="plugin-name"
          value={name}
          onChange={(event) =>
            setDraft({ name: event.target.value, description })
          }
          variant={pending ? "disabled" : "primary"}
        />
      </InputVertical>
      <InputVertical
        title={t("addMcpModal.description.title")}
        withLabel="plugin-description"
      >
        <InputTextArea
          id="plugin-description"
          value={description}
          onChange={(event) =>
            setDraft({ name, description: event.target.value })
          }
          variant={pending ? "disabled" : "primary"}
          rows={3}
        />
      </InputVertical>
      {error && (
        <Text as="p" color="status-error-05">
          {error}
        </Text>
      )}
      <MCPFormActions
        variant="page"
        active={active}
        footerTarget={footerTarget}
        submit={
          <Button
            onClick={() => void save()}
            disabled={
              pending ||
              !name.trim() ||
              (name.trim() === tool.name &&
                description.trim() === tool.description)
            }
          >
            {t(
              pending
                ? "addOpenApiModal.submitButton.savingLabel"
                : "addOpenApiModal.submitButton.saveLabel"
            )}
          </Button>
        }
      />
    </div>
  );
}

export default function OpenAPIPluginDetailPage({
  toolId,
}: OpenAPIPluginDetailPageProps) {
  const t = useTranslations("actions");
  const router = useRouter();
  const searchParams = useSearchParams();
  const {
    openApiTools,
    isLoading,
    error: loadError,
    mutateOpenApiTools,
    refreshOpenApiTools,
  } = useOpenApiTools();
  const tool = openApiTools?.find((candidate) => candidate.id === toolId);
  const [tab, setTab] = useState("server");
  const [visited, setVisited] = useState(() => new Set(["server"]));
  const [busy, setBusy] = useState(false);
  const [metadataDirty, setMetadataDirty] = useState(false);
  const [schemaDirty, setSchemaDirty] = useState(false);
  const [authDirty, setAuthDirty] = useState(false);
  const guard = useUnsavedChangesGuard({
    isDirty: metadataDirty || schemaDirty || authDirty,
  });
  const [footerTarget, setFooterTarget] = useState<HTMLDivElement | null>(null);
  const [toolSearch, setToolSearch] = useState("");
  const consumedConfigure = useRef(new Set<number>());
  const authenticationSession = useRef<{
    toolId: number;
    pendingOAuthConfigId: number | null;
    savedAuthentication?: { oauthConfigId: number | null; formKey: string };
  }>({ toolId, pendingOAuthConfigId: null });
  const active = useRef(true);
  const canEdit = can(tool, "edit");
  const canAuthenticate = can(tool, "authenticate");
  const savedAuthentication = authenticationSession.current.savedAuthentication;
  const authenticationFormKey =
    savedAuthentication &&
    (tool?.oauth_config_id ?? null) === savedAuthentication.oauthConfigId
      ? savedAuthentication.formKey
      : `${toolId}:${tool?.oauth_config_id ?? "none"}`;

  useEffect(() => {
    active.current = true;
    authenticationSession.current = { toolId, pendingOAuthConfigId: null };
    return () => {
      active.current = false;
    };
  }, [toolId]);

  useEffect(() => {
    if (
      !tool ||
      searchParams.get("configure") !== "authentication" ||
      consumedConfigure.current.has(tool.id)
    )
      return;
    consumedConfigure.current.add(tool.id);
    const next = new URLSearchParams(searchParams.toString());
    next.delete("configure");
    router.replace(
      withPluginSearchParams(
        pluginDetailHref({ kind: "openapi", id: tool.id }),
        next
      ),
      { scroll: false }
    );
    if (can(tool, "authenticate")) {
      setTab("authentication");
      setVisited((current) => new Set([...current, "authentication"]));
    }
  }, [tool, searchParams, router]);

  function closeDetail() {
    if (busy) return;
    guard.requestLeave(() =>
      router.replace("/admin/plugins", { scroll: false })
    );
  }

  async function saveMetadata(
    values: Pick<ToolSnapshot, "name" | "description">
  ) {
    if (!tool || !can(tool, "edit")) return;
    const tools = await refreshOpenApiTools();
    const currentTool = tools?.find((candidate) => candidate.id === tool.id);
    if (!currentTool || !can(currentTool, "edit")) {
      const message = t("addOpenApiModal.toasts.updateFailed");
      toast.error(message);
      throw new Error(message);
    }
    const response = await updateCustomTool(currentTool.id, {
      ...values,
      oauth_config_id: currentTool.oauth_config_id ?? null,
    });
    if (response.error || !response.data)
      throw new Error(
        response.error ?? t("addOpenApiModal.toasts.updateFailed")
      );
    await mutateOpenApiTools();
    toast.success(t("addOpenApiModal.toasts.actionUpdated"));
  }

  async function saveAuthentication(values: OpenAPIAuthFormValues) {
    if (!tool || !can(tool, "authenticate")) return;
    const session = authenticationSession.current;
    const sourceOAuthConfigId = tool.oauth_config_id ?? null;
    const tools = await refreshOpenApiTools();
    const currentTool = tools?.find(
      (candidate) => candidate.id === session.toolId
    );
    if (!currentTool || !can(currentTool, "authenticate")) {
      const message = t("addOpenApiModal.editConfigsButton.disabledTooltip");
      toast.error(message);
      throw new Error(message);
    }
    const currentOAuthConfigId = currentTool.oauth_config_id ?? null;
    if (
      currentOAuthConfigId !== sourceOAuthConfigId &&
      (currentOAuthConfigId !== session.savedAuthentication?.oauthConfigId ||
        authenticationFormKey !== session.savedAuthentication?.formKey)
    ) {
      const message = t("openApiPage.toasts.authSaveFailed");
      toast.error(message);
      throw new Error(message);
    }
    await saveOpenApiAuthentication({
      tool: currentTool,
      values,
      pendingOAuthConfigId: session.pendingOAuthConfigId,
      onOAuthConfigCreated: (id) => {
        session.pendingOAuthConfigId = id;
      },
    });
    session.savedAuthentication = {
      oauthConfigId:
        values.authMethod === "oauth"
          ? (currentOAuthConfigId ?? session.pendingOAuthConfigId)
          : null,
      formKey: authenticationFormKey,
    };
    if (values.authMethod === "oauth") session.pendingOAuthConfigId = null;
    await refreshOpenApiTools();
    if (active.current && authenticationSession.current === session)
      toast.success(
        t("openApiPage.toasts.authSaved", { name: currentTool.name })
      );
  }

  const methods = extractMethodSpecsFromDefinition(tool?.definition);
  const serverUrl = tool?.definition?.servers?.[0]?.url ?? "";
  const filteredMethods = methods.filter((method) =>
    `${method.name} ${method.summary ?? ""} ${method.path}`
      .toLowerCase()
      .includes(toolSearch.trim().toLowerCase())
  );
  const authMethod = tool?.oauth_config_id
    ? "oauth"
    : tool?.passthrough_auth
      ? "pt-oauth"
      : tool?.custom_headers.length
        ? "custom-header"
        : "none";
  const authDescription = {
    oauth: t("openApiAuthModal.authMethod.oauth.label"),
    "pt-oauth": t("openApiAuthModal.authMethod.ptOauth.label"),
    "custom-header": t("openApiAuthModal.authMethod.customHeader.label"),
    none: t("mcpAuthModal.authType.none.label"),
  }[authMethod];

  function selectTab(value: string) {
    if (busy) return;
    setTab(value);
    setVisited((current) => new Set([...current, value]));
  }

  return (
    <Modal
      open
      onOpenChange={(next) =>
        !next && (guard.confirmationOpen ? guard.cancelLeave() : closeDetail())
      }
    >
      <PluginModalContent>
        {!guard.confirmationOpen && (
          <Modal.Header
            title={tool?.name ?? t("plugins.openapi.detailsTitle")}
            icon={tool ? getActionIcon(serverUrl, tool.name) : SvgActions}
            description={
              serverUrl ||
              tool?.description ||
              t("plugins.openapi.detailDescription")
            }
            onClose={closeDetail}
          />
        )}
        <div className={guard.confirmationOpen ? "hidden" : "contents"}>
          <Modal.Body twoTone={false} alignItems="stretch">
            {!tool && isLoading ? (
              <IconLoader />
            ) : !tool ? (
              <div className="flex flex-col items-start gap-4">
                <Content
                  sizePreset="section"
                  variant="section"
                  title={t(
                    loadError
                      ? "plugins.openapi.loadFailed"
                      : "plugins.openapi.notFound"
                  )}
                  description={t("plugins.openapi.unavailable")}
                />
                {loadError && (
                  <Button
                    prominence="secondary"
                    onClick={() => void mutateOpenApiTools()}
                  >
                    {t("mcpDetail.retry")}
                  </Button>
                )}
              </div>
            ) : (
              <Tabs
                value={tab}
                onValueChange={selectTab}
                variant="contained"
                gap={6}
              >
                <Tabs.List>
                  <Tabs.Trigger value="server" disabled={busy}>
                    {t("plugins.openapi.detailsTitle")}
                  </Tabs.Trigger>
                  <Tabs.Trigger value="schema" disabled={busy}>
                    {t("plugins.openapi.schemaTitle")}
                  </Tabs.Trigger>
                  <Tabs.Trigger value="authentication" disabled={busy}>
                    {t("mcpDetail.authentication")}
                  </Tabs.Trigger>
                  <Tabs.Trigger value="tools" disabled={busy}>
                    {t("mcpTools.title")}
                  </Tabs.Trigger>
                </Tabs.List>
                <Tabs.Content
                  value="server"
                  keepMounted
                  hidden={tab !== "server"}
                >
                  <div className="h-[min(24rem,45dvh)] overflow-y-auto">
                    {canEdit ? (
                      <MetadataEditor
                        key={tool.id}
                        tool={tool}
                        active={tab === "server"}
                        footerTarget={footerTarget}
                        onBusyChange={setBusy}
                        onDirtyChange={setMetadataDirty}
                        onSave={saveMetadata}
                      />
                    ) : (
                      <Content
                        sizePreset="main-ui"
                        variant="section"
                        title={tool.name}
                        description={
                          tool.description || t("plugins.openapi.readOnly")
                        }
                      />
                    )}
                  </div>
                </Tabs.Content>
                <Tabs.Content
                  value="schema"
                  keepMounted
                  hidden={tab !== "schema"}
                >
                  <div className="h-[min(24rem,45dvh)] overflow-y-auto">
                    {visited.has("schema") &&
                      (canEdit ? (
                        <AddOpenAPIActionModal
                          presentation="inline"
                          active={tab === "schema"}
                          footerTarget={footerTarget}
                          onBusyChange={setBusy}
                          onDirtyChange={setSchemaDirty}
                          existingTool={tool}
                          onViewTools={() => selectTab("tools")}
                          onUpdate={async () => {
                            await mutateOpenApiTools();
                          }}
                        />
                      ) : (
                        <InputTextArea
                          value={JSON.stringify(tool.definition, null, 2)}
                          variant="disabled"
                          rows={12}
                          aria-label={t("plugins.openapi.schemaTitle")}
                        />
                      ))}
                  </div>
                </Tabs.Content>
                <Tabs.Content
                  value="authentication"
                  keepMounted
                  hidden={tab !== "authentication"}
                >
                  <div className="h-[min(24rem,45dvh)] overflow-y-auto">
                    {visited.has("authentication") &&
                      (canAuthenticate ? (
                        <OpenAPIAuthenticationModal
                          key={authenticationFormKey}
                          presentation="inline"
                          active={tab === "authentication"}
                          footerTarget={footerTarget}
                          onBusyChange={setBusy}
                          onDirtyChange={setAuthDirty}
                          isOpen
                          title={t("mcpDetail.authentication")}
                          allowNoAuthentication
                          defaultMethod={authMethod}
                          onClose={closeDetail}
                          submitLabel={t(
                            "addOpenApiModal.submitButton.saveLabel"
                          )}
                          oauthConfigId={tool.oauth_config_id ?? null}
                          initialHeaders={tool.custom_headers}
                          passthroughOAuthEnabled={tool.passthrough_auth}
                          onConnect={saveAuthentication}
                        />
                      ) : (
                        <Content
                          sizePreset="main-ui"
                          variant="section"
                          title={t("mcpDetail.authentication")}
                          description={authDescription}
                        />
                      ))}
                  </div>
                </Tabs.Content>
                <Tabs.Content value="tools">
                  <div className="flex h-[min(24rem,45dvh)] flex-col gap-4 overflow-y-auto">
                    <InputTypeIn
                      searchIcon
                      value={toolSearch}
                      onChange={(event) => setToolSearch(event.target.value)}
                      placeholder={t("mcpTools.search")}
                      aria-label={t("mcpTools.search")}
                    />
                    {filteredMethods.length ? (
                      <OpenAPIEndpointList methods={filteredMethods} />
                    ) : (
                      <Text as="p" color="text-03">
                        {t(
                          toolSearch.trim()
                            ? "toolsList.empty.searchMessage"
                            : "toolsList.empty.message"
                        )}
                      </Text>
                    )}
                  </div>
                </Tabs.Content>
              </Tabs>
            )}
          </Modal.Body>
          <Modal.Footer padding={4}>
            <div
              ref={setFooterTarget}
              className="ms-auto flex min-h-8 items-center gap-2"
            />
          </Modal.Footer>
        </div>
        {guard.confirmationOpen && (
          <UnsavedChangesModalContent
            onCancel={guard.cancelLeave}
            onDiscard={guard.discardAndLeave}
          />
        )}
      </PluginModalContent>
    </Modal>
  );
}
