"use client";

import isEqual from "lodash/isEqual";
import { useId, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Button, InputTypeIn, Modal, Tabs, Text } from "@opal/components";
import { Content } from "@opal/layouts";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { ActionPolicy } from "@/app/craft/v1/apps/registry";
import type { AppActionPoliciesView } from "@/lib/plugins/types";
import { saveAppActionPolicies } from "@/app/craft/services/apiServices";
import PolicyEditor from "@/sections/actions/PolicyEditor";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";
import { UnsavedChangesModalContent } from "@/sections/modals/UnsavedChangesModal";
import PluginModalContent from "@/sections/plugins/PluginModalContent";
import MemberMCPToolsList from "@/sections/plugins/MemberMCPToolsList";
import MemberCraftAppSkills from "@/sections/plugins/MemberCraftAppSkills";
import OpenAPIEndpointList from "@/sections/plugins/OpenAPIEndpointList";
import { SvgFileBraces, SvgUnplug } from "@opal/icons";
import MemberMCPPreferences from "@/sections/plugins/MemberMCPPreferences";
import MemberOpenAPIPreferences from "@/sections/plugins/MemberOpenAPIPreferences";
import type { ToolSnapshot } from "@/lib/tools/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { cn } from "@opal/utils";
import {
  extractMethodSpecsFromDefinition,
  getActionIcon,
} from "@/lib/tools/utils";
import { getAppTypeLogo } from "@/app/craft/v1/apps/registry";
import { CRAFT_PATH } from "@/app/craft/v1/constants";
import useUserSkills from "@/hooks/useUserSkills";
import { useSettings } from "@/lib/settings/hooks";
import {
  canUseMemberPlugin,
  disconnectMemberPlugin,
  memberPluginName,
  type MemberPlugin,
} from "@/lib/plugins/member";

interface MemberPluginDetailModalProps {
  plugin: MemberPlugin;
  surface?: "all" | "craft";
  open: boolean;
  initialTab?: "connection" | "approvals";
  onClose: () => void;
  onConnect: () => void;
  onUseInChat: () => void;
  onOpenInCraft?: () => void;
  onDisconnected: () => void;
}

type DetailAction =
  | { kind: "details" }
  | { kind: "confirmDisconnect" }
  | { kind: "disconnecting" }
  | { kind: "disconnectError" };

interface MemberDetailTabsProps {
  enabled: boolean;
  tab: string;
  onTabChange: (value: string) => void;
  connection: ReactNode;
  capabilities: ReactNode;
  secondaryTab?: "tools" | "skills";
  approvals?: ReactNode;
}

function MemberDetailTabs({
  enabled,
  tab,
  onTabChange,
  connection,
  capabilities,
  secondaryTab = "tools",
  approvals,
}: MemberDetailTabsProps) {
  const t = useTranslations("actions.memberPlugins");
  const approvalCopy = useTranslations("craft.actionPolicies");
  const craftTabs = useTranslations("actions.plugins.craftApp.tabs");
  if (!enabled)
    return (
      <>
        {connection}
        {capabilities}
      </>
    );
  return (
    <Tabs value={tab} onValueChange={onTabChange} variant="contained" gap={6}>
      <Tabs.List>
        <Tabs.Trigger value="connection">{t("detail.connection")}</Tabs.Trigger>
        {capabilities && (
          <Tabs.Trigger value={secondaryTab}>
            {secondaryTab === "skills"
              ? craftTabs("skills")
              : t("detail.tools")}
          </Tabs.Trigger>
        )}
        {approvals && (
          <Tabs.Trigger value="approvals">{approvalCopy("title")}</Tabs.Trigger>
        )}
      </Tabs.List>
      <Tabs.Content
        value="connection"
        keepMounted
        hidden={tab !== "connection"}
      >
        <div className="flex flex-col gap-6">{connection}</div>
      </Tabs.Content>
      {capabilities && (
        <Tabs.Content value={secondaryTab}>{capabilities}</Tabs.Content>
      )}
      {approvals && (
        <Tabs.Content
          value="approvals"
          keepMounted
          hidden={tab !== "approvals"}
        >
          {approvals}
        </Tabs.Content>
      )}
    </Tabs>
  );
}

function ExternalAppSkillRecovery({ appId }: { appId: number }) {
  const t = useTranslations("craft.apps.page");
  const { data: skills } = useUserSkills();
  const needsSkills = [
    ...(skills?.builtins ?? []),
    ...(skills?.customs ?? []),
  ].some(
    (skill) => skill.external_app?.external_app_id === appId && !skill.enabled
  );
  if (!needsSkills) return null;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 pt-4">
      <Text font="secondary-body" color="text-03">
        {t("status.connectedNeedsSkills")}
      </Text>
      <Button
        size="sm"
        prominence="secondary"
        href={`/craft/v1/skills?externalAppId=${appId}`}
      >
        {t("reviewSkillsButton")}
      </Button>
    </div>
  );
}

export default function MemberPluginDetailModal({
  plugin,
  surface = "all",
  open,
  initialTab = "connection",
  onClose,
  onConnect,
  onUseInChat,
  onOpenInCraft,
  onDisconnected,
}: MemberPluginDetailModalProps) {
  const t = useTranslations("actions.memberPlugins");
  const craftEnabled = useSettings().onyx_craft_enabled === true;
  const actions = useTranslations("actions");
  const craftCopy = useTranslations("craft.apps.page");
  const [action, setAction] = useState<DetailAction>({ kind: "details" });
  const [tab, setTab] = useState<string>(
    initialTab === "approvals" &&
      craftEnabled &&
      plugin.kind !== "openapi" &&
      (plugin.kind === "external-app" ||
        plugin.server.available_in_craft === true)
      ? "approvals"
      : "connection"
  );
  const approvalCopy = useTranslations("craft.actionPolicies");
  const [approvalsOpened, setApprovalsOpened] = useState(
    initialTab === "approvals"
  );
  const openingId = useId();
  const [policyApp, setPolicyApp] = useState<AppActionPoliciesView | null>(
    null
  );
  const [initialPolicies, setInitialPolicies] = useState<
    Record<string, ActionPolicy>
  >({});
  const [policies, setPolicies] = useState<Record<string, ActionPolicy>>({});
  const [savingPolicies, setSavingPolicies] = useState(false);
  const [policySaveError, setPolicySaveError] = useState<string | null>(null);
  const supportsApprovals =
    craftEnabled &&
    plugin.kind !== "openapi" &&
    (plugin.kind === "external-app" ||
      plugin.server.available_in_craft === true);
  const showApprovals =
    supportsApprovals && plugin.connection.kind === "connected";
  const activeTab = tab === "approvals" && !showApprovals ? "connection" : tab;
  const policyTarget =
    plugin.kind === "external-app"
      ? { kind: "external_app" as const, id: plugin.app.id }
      : plugin.kind === "mcp"
        ? { kind: "mcp_server" as const, id: plugin.server.id }
        : null;
  const { error: policyLoadError, mutate: refreshPolicies } = useSWR<
    AppActionPoliciesView,
    Error
  >(
    open && approvalsOpened && showApprovals && policyTarget
      ? [
          SWR_KEYS.appActionPolicies(policyTarget.kind, policyTarget.id),
          openingId,
        ]
      : null,
    ([url]: [string, string]) => errorHandlingFetcher(url),
    {
      revalidateOnMount: true,
      revalidateOnFocus: false,
      onSuccess: (app) => {
        if (policyApp !== null) return;
        const choices = Object.fromEntries(
          app.actions
            .filter((item) => item.editable || item.stored_policy !== null)
            .map((item) => [
              item.action_id,
              item.stored_policy ?? item.effective_policy,
            ])
        );
        setPolicyApp(app);
        setInitialPolicies(choices);
        setPolicies(choices);
      },
    }
  );
  const policiesDirty = !isEqual(policies, initialPolicies);
  const guard = useUnsavedChangesGuard({
    isDirty: policiesDirty,
    onDiscard: () => setPolicies(initialPolicies),
  });

  async function savePolicies() {
    if (!policyApp || savingPolicies) return;
    setSavingPolicies(true);
    setPolicySaveError(null);
    try {
      await saveAppActionPolicies(
        policyApp.gated_app_id,
        policies,
        approvalCopy("saveError")
      );
      setInitialPolicies(policies);
      onClose();
    } catch (error) {
      setPolicySaveError(
        error instanceof Error ? error.message : approvalCopy("saveError")
      );
    } finally {
      setSavingPolicies(false);
    }
  }
  const [endpointSearch, setEndpointSearch] = useState("");
  const { data: memberTools } = useSWR<ToolSnapshot[]>(
    plugin.kind === "openapi" ? SWR_KEYS.tools : null,
    null,
    { revalidateOnMount: false }
  );
  const openAPITool =
    plugin.kind === "openapi"
      ? (memberTools?.find((tool) => tool.id === plugin.tool.id) ?? plugin.tool)
      : null;
  const name = memberPluginName(plugin);
  const connection = plugin.connection;
  const schemaServers: unknown =
    plugin.kind === "openapi" ? plugin.tool.definition?.servers : undefined;
  const schemaServer: unknown = Array.isArray(schemaServers)
    ? schemaServers[0]
    : undefined;
  const serverUrl =
    plugin.kind === "external-app"
      ? plugin.app.service_urls?.join(", ")
      : plugin.kind === "mcp"
        ? plugin.server.server_url
        : typeof schemaServer === "object" &&
            schemaServer !== null &&
            "url" in schemaServer &&
            typeof schemaServer.url === "string"
          ? schemaServer.url
          : undefined;
  const endpoints =
    plugin.kind === "openapi"
      ? extractMethodSpecsFromDefinition(plugin.tool.definition)
      : [];
  const endpointQuery = endpointSearch.trim().toLocaleLowerCase();
  const visibleEndpoints = endpoints.filter((endpoint) =>
    [endpoint.name, endpoint.summary, endpoint.path, endpoint.method].some(
      (value) => value.toLocaleLowerCase().includes(endpointQuery)
    )
  );
  const hasTabs =
    plugin.kind === "external-app"
      ? craftEnabled
      : surface !== "craft" || showApprovals;
  const chatEnabled =
    plugin.kind === "external-app"
      ? false
      : plugin.kind === "mcp"
        ? plugin.server.default_chat_enabled
        : openAPITool?.default_chat_enabled;
  const icon =
    plugin.kind === "external-app"
      ? getAppTypeLogo(plugin.app.app_type)
      : plugin.kind === "mcp"
        ? getActionIcon(plugin.server.server_url, plugin.server.name)
        : (getActionIcon(serverUrl ?? "", name) ?? SvgFileBraces);
  const canDisconnect =
    connection.kind === "connected" && connection.ownership === "user";
  const canConnect =
    connection.kind === "oauth" || connection.kind === "credentials";
  const confirming = action.kind !== "details";
  const pending = action.kind === "disconnecting" || savingPolicies;

  function close() {
    if (!pending) guard.requestLeave(onClose);
  }

  async function disconnect() {
    setAction({ kind: "disconnecting" });
    try {
      await disconnectMemberPlugin(plugin);
      onDisconnected();
    } catch {
      setAction({ kind: "disconnectError" });
    }
  }

  const connectionLabel =
    connection.kind === "connected"
      ? t(
          `status.${connection.ownership === "user" ? "connected" : connection.ownership}`
        )
      : t(`status.${connection.kind}`);
  const headerStatus = canConnect ? t("filters.needsSignIn") : connectionLabel;

  if (guard.confirmationOpen) {
    return (
      <Modal open={open} onOpenChange={(next) => !next && guard.cancelLeave()}>
        <PluginModalContent>
          <UnsavedChangesModalContent
            onCancel={guard.cancelLeave}
            onDiscard={guard.discardAndLeave}
          />
        </PluginModalContent>
      </Modal>
    );
  }

  return (
    <Modal open={open} onOpenChange={(next) => !next && close()}>
      <PluginModalContent>
        <Modal.Header
          icon={icon}
          title={
            confirming
              ? t("detail.disconnectTitle", { name })
              : activeTab === "approvals"
                ? approvalCopy("appTitle", { name })
                : name
          }
          description={
            confirming ? t("detail.disconnectDescription") : undefined
          }
          onClose={close}
          gap={!confirming ? 1 : undefined}
        >
          {!confirming && (
            <div className="flex w-full min-w-0 items-center justify-between gap-4 px-2">
              {serverUrl && (
                <div className="min-w-0 flex-1">
                  <Text
                    font="secondary-body"
                    color="text-03"
                    wordWrap="wrap-anywhere"
                  >
                    {serverUrl}
                  </Text>
                </div>
              )}
              <div
                role="status"
                className="ms-auto flex shrink-0 items-center gap-2"
              >
                <span
                  aria-hidden
                  className={cn(
                    "size-2 rounded-full",
                    connection.kind === "connected"
                      ? "bg-status-success-05"
                      : canConnect
                        ? "bg-status-warning-05"
                        : "bg-text-03"
                  )}
                />
                <Text font="secondary-body" color="text-03">
                  {headerStatus}
                </Text>
              </div>
            </div>
          )}
        </Modal.Header>
        <Modal.Body twoTone={false} alignItems="stretch">
          {confirming ? (
            <>
              {plugin.kind === "openapi" && (
                <Text as="p" font="main-ui-body" color="text-03">
                  {t("detail.oauthDisconnectWarning")}
                </Text>
              )}
              {action.kind === "disconnectError" && (
                <div role="alert">
                  <Text color="status-error-05">
                    {t("detail.disconnectFailed")}
                  </Text>
                </div>
              )}
            </>
          ) : (
            <MemberDetailTabs
              enabled={hasTabs}
              secondaryTab={plugin.kind === "external-app" ? "skills" : "tools"}
              tab={activeTab}
              onTabChange={(next) => {
                if (!pending) {
                  setTab(next);
                  if (next === "approvals") setApprovalsOpened(true);
                }
              }}
              approvals={
                showApprovals ? (
                  <div className="flex flex-col gap-4">
                    <Text font="secondary-body" color="text-03">
                      {approvalCopy("personalDescription")}
                    </Text>
                    {policyApp ? (
                      <PolicyEditor
                        showTitle={false}
                        showDescription={false}
                        items={policyApp.actions.map((item) => ({
                          id: item.action_id,
                          name: item.normalised_name,
                          description: item.description,
                          defaultPolicy: item.editable
                            ? item.workspace_policy
                            : item.effective_policy,
                          editable: item.editable,
                          lockReason: item.lock_reason ?? undefined,
                        }))}
                        policies={policies}
                        onChange={setPolicies}
                        onReset={() => setPolicies({})}
                        resetLabel={approvalCopy("resetAll")}
                        disabled={
                          savingPolicies || !policyApp.users_can_manage_policies
                        }
                      />
                    ) : (
                      <Text font="secondary-body">
                        {approvalCopy(
                          policyLoadError ? "loadError" : "loading"
                        )}
                      </Text>
                    )}
                    {!policyApp && policyLoadError && (
                      <Button
                        prominence="secondary"
                        onClick={() => void refreshPolicies()}
                      >
                        {approvalCopy("retry")}
                      </Button>
                    )}
                    {policySaveError && (
                      <Text role="alert" color="status-error-05">
                        {policySaveError}
                      </Text>
                    )}
                  </div>
                ) : undefined
              }
              connection={
                <>
                  {plugin.kind === "mcp" && (
                    <MemberMCPPreferences
                      server={plugin.server}
                      surface={surface}
                    />
                  )}
                  {plugin.kind === "openapi" && (
                    <>
                      {plugin.tool.description && (
                        <Content
                          sizePreset="main-ui"
                          variant="section"
                          title={actions("addMcpModal.description.title")}
                          description={plugin.tool.description}
                        />
                      )}
                      {surface !== "craft" && (
                        <MemberOpenAPIPreferences
                          tool={openAPITool ?? plugin.tool}
                        />
                      )}
                    </>
                  )}
                  {plugin.kind === "external-app" && craftEnabled && (
                    <Text as="p" font="secondary-body" color="text-03">
                      {t("externalApp.craftOnlyDescription")}
                    </Text>
                  )}
                  {plugin.kind === "external-app" &&
                    craftEnabled &&
                    connection.kind === "connected" && (
                      <ExternalAppSkillRecovery appId={plugin.app.id} />
                    )}
                </>
              }
              capabilities={
                hasTabs &&
                (surface !== "craft" || plugin.kind === "external-app") &&
                (plugin.kind === "external-app" ? (
                  <MemberCraftAppSkills appId={plugin.app.id} />
                ) : plugin.kind === "mcp" ? (
                  <MemberMCPToolsList tools={plugin.tools} />
                ) : (
                  <div className="flex flex-col gap-4">
                    <div className="flex items-center gap-4">
                      <div className="min-w-0 flex-1">
                        <InputTypeIn
                          searchIcon
                          value={endpointSearch}
                          onChange={(event) =>
                            setEndpointSearch(event.target.value)
                          }
                          placeholder={actions("mcpTools.search")}
                          aria-label={actions("mcpTools.search")}
                        />
                      </div>
                      <Text font="secondary-body" color="text-03">
                        {t("detail.toolCount", {
                          count: visibleEndpoints.length,
                        })}
                      </Text>
                    </div>
                    {visibleEndpoints.length ? (
                      <OpenAPIEndpointList methods={visibleEndpoints} />
                    ) : (
                      <Text font="secondary-body" color="text-03">
                        {endpoints.length
                          ? actions("toolsList.empty.searchMessage")
                          : t("detail.noTools")}
                      </Text>
                    )}
                  </div>
                ))
              }
            />
          )}
        </Modal.Body>
        <Modal.Footer wrap>
          {confirming ? (
            <>
              <Button
                prominence="secondary"
                disabled={pending}
                onClick={() => setAction({ kind: "details" })}
              >
                {t("detail.cancel")}
              </Button>
              <Button
                variant="danger"
                disabled={pending}
                onClick={() => void disconnect()}
              >
                {t(pending ? "detail.disconnecting" : "detail.disconnect")}
              </Button>
            </>
          ) : (
            <>
              {canDisconnect && (!hasTabs || activeTab === "connection") && (
                <div className="flex flex-1">
                  <Button
                    prominence="tertiary"
                    icon={SvgUnplug}
                    onClick={() =>
                      guard.requestLeave(() =>
                        setAction({ kind: "confirmDisconnect" })
                      )
                    }
                  >
                    {t("detail.disconnect")}
                  </Button>
                </div>
              )}
              {plugin.kind === "external-app" &&
                craftEnabled &&
                activeTab === "skills" && (
                  <div className="flex flex-1">
                    <Button
                      prominence="tertiary"
                      href={`/craft/v1/skills?externalAppId=${plugin.app.id}`}
                    >
                      {craftCopy("reviewSkillsButton")}
                    </Button>
                  </div>
                )}
              <Button prominence="secondary" disabled={pending} onClick={close}>
                {t("detail.close")}
              </Button>
              {activeTab === "approvals" &&
                policyApp?.users_can_manage_policies && (
                  <Button
                    disabled={pending || !policiesDirty}
                    onClick={() => void savePolicies()}
                  >
                    {approvalCopy("save")}
                  </Button>
                )}
              {canConnect && (
                <Button
                  disabled={pending}
                  onClick={() => guard.requestLeave(onConnect)}
                >
                  {t("detail.connect")}
                </Button>
              )}
              {craftEnabled &&
                (plugin.kind === "external-app"
                  ? canUseMemberPlugin(plugin)
                  : surface === "craft") && (
                  <Button
                    href={onOpenInCraft ? undefined : CRAFT_PATH}
                    disabled={pending}
                    onClick={
                      onOpenInCraft
                        ? () => guard.requestLeave(onOpenInCraft)
                        : undefined
                    }
                  >
                    {t("detail.openInCraft")}
                  </Button>
                )}
              {plugin.kind !== "external-app" &&
                surface !== "craft" &&
                canUseMemberPlugin(plugin) &&
                (plugin.kind === "mcp"
                  ? (plugin.server.user_enabled_in_chat ?? true)
                  : (openAPITool?.user_enabled_in_chat ?? true)) &&
                chatEnabled === true && (
                  <Button
                    disabled={pending}
                    onClick={() => guard.requestLeave(onUseInChat)}
                  >
                    {t("detail.useInChat")}
                  </Button>
                )}
            </>
          )}
        </Modal.Footer>
      </PluginModalContent>
    </Modal>
  );
}
