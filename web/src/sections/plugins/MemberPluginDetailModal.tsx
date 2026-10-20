"use client";

import isEqual from "lodash/isEqual";
import { useId, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import {
  Button,
  Card,
  Divider,
  InputTypeIn,
  Modal,
  Tabs,
  Text,
} from "@opal/components";
import useSWR, { useSWRConfig } from "swr";
import type {
  MCPUserPreferences,
  MCPUserPreferencesRequest,
} from "@/lib/mcp/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { ActionPolicy } from "@/app/craft/v1/apps/registry";
import type { AppActionPoliciesView } from "@/lib/plugins/types";
import { saveAppActionPolicies } from "@/app/craft/services/apiServices";
import { SkillPreviewContent } from "@/sections/modals/SkillPreviewModal";
import PolicyEditor from "@/sections/actions/PolicyEditor";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";
import { UnsavedChangesModalContent } from "@/sections/modals/UnsavedChangesModal";
import PluginModalContent from "@/sections/plugins/PluginModalContent";
import MemberMCPToolsList from "@/sections/plugins/MemberMCPToolsList";
import MemberCraftAppSkills from "@/sections/plugins/MemberCraftAppSkills";
import OpenAPIEndpointList from "@/sections/plugins/OpenAPIEndpointList";
import { SvgCodeFile } from "@opal/icons";
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
import { useExternalAppSkillIssues } from "@/lib/externalApps/hooks";
import { isSkillNameConflict, setSkillEnabled } from "@/lib/skills/api";
import useUserSkills from "@/hooks/useUserSkills";
import type { Skill, SkillsList } from "@/lib/skills/types";
import { useSettings } from "@/lib/settings/hooks";
import {
  saveMemberMCPPreferences,
  saveMemberOpenAPIPreferences,
  disconnectMemberPlugin,
  memberPluginName,
  type MemberPlugin,
} from "@/lib/plugins/member";

interface MemberPluginDetailModalProps {
  plugin: MemberPlugin;
  surface?: "all" | "craft";
  open: boolean;
  skipOverlay?: boolean;
  initialTab?: "connection" | "approvals";
  onClose: () => void;
  onConnect: () => void;
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
  approvalsLoading: boolean;
  availableActions?: ReactNode;
}

function MemberDetailTabs({
  enabled,
  tab,
  onTabChange,
  connection,
  capabilities,
  secondaryTab = "tools",
  approvals,
  approvalsLoading,
  availableActions,
}: MemberDetailTabsProps) {
  const t = useTranslations("actions.memberPlugins");
  const toolCopy = useTranslations("actions.mcpTools");
  const craftTabs = useTranslations("actions.plugins.craftApp.tabs");
  if (!enabled)
    return (
      <>
        {connection}
        {capabilities}
      </>
    );
  const toolsTab = tab === "approvals" ? "tools" : tab;
  const availableTools =
    secondaryTab === "tools"
      ? capabilities || availableActions
      : availableActions;
  return (
    <Tabs
      value={toolsTab}
      onValueChange={onTabChange}
      variant="contained"
      gap={6}
    >
      <Tabs.List>
        <Tabs.Trigger value="connection">{t("detail.connection")}</Tabs.Trigger>
        {(availableTools || approvals) && (
          <Tabs.Trigger value="tools">{t("detail.tools")}</Tabs.Trigger>
        )}
        {secondaryTab === "skills" && capabilities && (
          <Tabs.Trigger value="skills">{craftTabs("skills")}</Tabs.Trigger>
        )}
      </Tabs.List>
      <Tabs.Content
        value="connection"
        keepMounted
        hidden={toolsTab !== "connection"}
      >
        <div className="flex flex-col gap-6">{connection}</div>
      </Tabs.Content>
      <Tabs.Content value="tools">
        {secondaryTab === "skills" ? (
          approvals
        ) : approvals ? (
          <Tabs
            value={tab === "approvals" ? "approvals" : "available"}
            onValueChange={(value) =>
              onTabChange(value === "approvals" ? "approvals" : "tools")
            }
            variant="underline"
            gap={4}
          >
            <Tabs.List>
              <Tabs.Trigger value="available">
                {toolCopy("enabledTab")}
              </Tabs.Trigger>
              <Tabs.Trigger
                value="approvals"
                isLoading={tab === "approvals" && approvalsLoading}
              >
                {toolCopy("policiesTab")}
              </Tabs.Trigger>
            </Tabs.List>
            <Tabs.Content value="available">{availableTools}</Tabs.Content>
            <Tabs.Content value="approvals">
              {approvalsLoading ? availableTools : approvals}
            </Tabs.Content>
          </Tabs>
        ) : (
          availableTools
        )}
      </Tabs.Content>
      {secondaryTab === "skills" && (
        <Tabs.Content value="skills">{capabilities}</Tabs.Content>
      )}
    </Tabs>
  );
}

function ExternalAppSkillRecovery({
  appId,
  onReview,
}: {
  appId: number;
  onReview: () => void;
}) {
  const t = useTranslations("craft.apps.page");
  const detailCopy = useTranslations("actions.memberPlugins.detail");
  const needsSkills = useExternalAppSkillIssues(appId);
  if (!needsSkills) return null;
  return (
    <Card border="solid" padding={4}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <span
            aria-hidden
            className="size-2 shrink-0 rounded-full bg-status-warning-05"
          />
          <div className="flex min-w-0 flex-col gap-1">
            <Text font="main-ui-action">{detailCopy("issuesTitle")}</Text>
            <Text font="secondary-body" color="text-03">
              {t("status.skillWarningTooltip")}
            </Text>
          </div>
        </div>
        <Button onClick={onReview}>{t("reviewSkillsButton")}</Button>
      </div>
    </Card>
  );
}

export default function MemberPluginDetailModal(
  props: MemberPluginDetailModalProps
) {
  return (
    <Modal open={props.open}>
      <MemberPluginDetailContent {...props} />
    </Modal>
  );
}

export function MemberPluginDetailContent({
  plugin,
  surface = "all",
  open,
  skipOverlay = false,
  initialTab = "connection",
  onClose,
  onConnect,
  onDisconnected,
}: MemberPluginDetailModalProps) {
  const t = useTranslations("actions.memberPlugins");
  const router = useRouter();
  const craftEnabled = useSettings().onyx_craft_enabled === true;
  const actions = useTranslations("actions");
  const switchCopy = useTranslations("skills.page.switchModal");
  const { data: skills } = useUserSkills(
    craftEnabled && plugin.kind === "external-app"
  );
  const [skillConflict, setSkillConflict] = useState<Skill | null>(null);
  const craftCopy = useTranslations("craft.apps.page");
  const [preview, setPreview] = useState<Skill | null>(null);
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
  const openingId = useId();
  const [policyApp, setPolicyApp] = useState<AppActionPoliciesView | null>(
    null
  );
  const [initialPolicies, setInitialPolicies] = useState<
    Record<string, ActionPolicy>
  >({});
  const [policies, setPolicies] = useState<Record<string, ActionPolicy>>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
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
    open && showApprovals && policyTarget
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
  const policyLoadState = (
    <>
      <Text font="secondary-body">
        {approvalCopy(policyLoadError ? "loadError" : "loading")}
      </Text>
      {policyLoadError && (
        <Button prominence="secondary" onClick={() => void refreshPolicies()}>
          {approvalCopy("retry")}
        </Button>
      )}
    </>
  );
  const { mutate } = useSWRConfig();
  const [initialPreferences, setInitialPreferences] =
    useState<MCPUserPreferences>(() => ({
      enabled_in_chat:
        plugin.kind === "mcp"
          ? (plugin.server.user_enabled_in_chat ?? true)
          : plugin.kind === "openapi"
            ? (plugin.tool.user_enabled_in_chat ?? true)
            : true,
      enabled_in_craft:
        plugin.kind === "mcp"
          ? (plugin.server.user_enabled_in_craft ?? true)
          : true,
    }));
  const [preferences, setPreferences] = useState(initialPreferences);
  const preferencesDirty = !isEqual(preferences, initialPreferences);
  const policiesDirty = !isEqual(policies, initialPolicies);
  const [skillChanges, setSkillChanges] = useState<Record<string, boolean>>({});
  const dirty =
    preferencesDirty || policiesDirty || Object.keys(skillChanges).length > 0;
  function changeSkill(skill: Skill, enabled: boolean) {
    setSkillChanges((current) => {
      const next = { ...current };
      if (enabled === skill.enabled) delete next[skill.id];
      else next[skill.id] = enabled;
      return next;
    });
  }
  const guard = useUnsavedChangesGuard({
    isDirty: dirty,
    onDiscard: () => {
      setPolicies(initialPolicies);
      setPreferences(initialPreferences);
      setSkillChanges({});
    },
  });

  function reviewSkills() {
    if (plugin.kind !== "external-app" || saving) return;
    guard.requestLeave(() =>
      router.push(`/craft/v1/skills?externalAppId=${plugin.app.id}`)
    );
  }

  async function saveChanges(replaceSkillId?: string) {
    if (
      saving ||
      !dirty ||
      (policiesDirty && !policyApp?.users_can_manage_policies)
    )
      return;
    setSaving(true);
    setSaveError(null);
    try {
      if (preferencesDirty) {
        if (plugin.kind === "mcp") {
          const chatChanged =
            preferences.enabled_in_chat !== initialPreferences.enabled_in_chat;
          const craftChanged =
            preferences.enabled_in_craft !==
            initialPreferences.enabled_in_craft;
          const changes: MCPUserPreferencesRequest = chatChanged
            ? { enabled_in_chat: preferences.enabled_in_chat }
            : { enabled_in_craft: preferences.enabled_in_craft };
          if (craftChanged)
            changes.enabled_in_craft = preferences.enabled_in_craft;
          await saveMemberMCPPreferences(plugin.server.id, changes, mutate);
        } else if (plugin.kind === "openapi") {
          await saveMemberOpenAPIPreferences(
            plugin.tool.id,
            { enabled_in_chat: preferences.enabled_in_chat },
            mutate
          );
        }
        setInitialPreferences(preferences);
      }
      if (policiesDirty && policyApp) {
        await saveAppActionPolicies(
          policyApp.gated_app_id,
          policies,
          approvalCopy("saveError")
        );
        setInitialPolicies(policies);
      }
      // Save disables first so switching between skills with the same name works.
      const changes = Object.entries(skillChanges).sort(
        (a, b) => Number(a[1]) - Number(b[1])
      );
      for (const [skillId, enabled] of changes) {
        let updated: Skill;
        try {
          updated = await setSkillEnabled(
            skillId,
            enabled,
            skillId === replaceSkillId
          );
        } catch (error) {
          const skill = [
            ...(skills?.builtins ?? []),
            ...(skills?.customs ?? []),
          ].find((item) => item.id === skillId);
          if (enabled && isSkillNameConflict(error) && skill) {
            setSkillConflict(skill);
            return;
          }
          throw error;
        }
        if (skillId === replaceSkillId) setSkillConflict(null);
        const updateSkill = (skill: Skill): Skill =>
          skill.id === updated.id
            ? updated
            : enabled && skill.name === updated.name
              ? { ...skill, enabled: false }
              : skill;
        await mutate<SkillsList>(
          SWR_KEYS.userSkills,
          (current) =>
            current && {
              builtins: current.builtins.map(updateSkill),
              customs: current.customs.map(updateSkill),
            },
          { revalidate: false }
        );
        setSkillChanges((current) => {
          const next = { ...current };
          delete next[skillId];
          return next;
        });
      }
      onClose();
    } catch (error) {
      setSaveError(
        error instanceof Error ? error.message : t("defaults.saveFailed")
      );
    } finally {
      setSaving(false);
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
  const description =
    plugin.kind === "mcp"
      ? plugin.server.description
      : plugin.kind === "openapi"
        ? plugin.tool.description
        : craftEnabled
          ? t("externalApp.craftOnlyDescription")
          : undefined;
  const connection = plugin.connection;
  const schemaServers: unknown =
    plugin.kind === "openapi" ? plugin.tool.definition?.servers : undefined;
  const schemaServer: unknown = Array.isArray(schemaServers)
    ? schemaServers[0]
    : undefined;
  const serverUrl =
    typeof schemaServer === "object" &&
    schemaServer !== null &&
    "url" in schemaServer &&
    typeof schemaServer.url === "string"
      ? schemaServer.url
      : "";
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
  const icon =
    plugin.kind === "external-app"
      ? getAppTypeLogo(plugin.app.app_type)
      : plugin.kind === "mcp"
        ? getActionIcon(plugin.server.server_url, plugin.server.name)
        : (getActionIcon(serverUrl, name) ?? SvgCodeFile);
  const canDisconnect =
    connection.kind === "connected" && connection.ownership === "user";
  const canConnect =
    connection.kind === "oauth" || connection.kind === "credentials";
  const confirming = action.kind !== "details";
  const pending = action.kind === "disconnecting" || saving;

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
  const connectionTitle =
    connection.kind === "connected"
      ? t(connection.ownership === "user" ? "status.connected" : "status.none")
      : connectionLabel;

  if (guard.confirmationOpen) {
    return (
      <PluginModalContent
        skipOverlay={skipOverlay}
        onEscapeKeyDown={(event) => {
          event.preventDefault();
          guard.cancelLeave();
        }}
        onInteractOutside={(event) => {
          if (event.defaultPrevented) return;
          event.preventDefault();
          guard.cancelLeave();
        }}
      >
        <UnsavedChangesModalContent
          onCancel={guard.cancelLeave}
          onDiscard={guard.discardAndLeave}
        />
      </PluginModalContent>
    );
  }

  function dismiss() {
    if (saving) return;
    if (skillConflict) setSkillConflict(null);
    else if (preview) setPreview(null);
    else close();
  }

  return (
    <PluginModalContent
      skipOverlay={skipOverlay}
      onEscapeKeyDown={(event) => {
        event.preventDefault();
        dismiss();
      }}
      onInteractOutside={(event) => {
        if (event.defaultPrevented) return;
        event.preventDefault();
        dismiss();
      }}
    >
      {skillConflict ? (
        <>
          <Modal.Header
            title={switchCopy("title", { name: skillConflict.name })}
            description={switchCopy("description", {
              name: skillConflict.name,
            })}
            onClose={saving ? undefined : () => setSkillConflict(null)}
          />
          <Modal.Body>
            <Text>{switchCopy("body")}</Text>
            {saveError && (
              <Text role="alert" color="status-error-05">
                {saveError}
              </Text>
            )}
          </Modal.Body>
          <Modal.Footer>
            <Button
              prominence="secondary"
              disabled={saving}
              onClick={() => setSkillConflict(null)}
            >
              {actions("mcpSetup.back")}
            </Button>
            <Button
              disabled={saving}
              onClick={() => void saveChanges(skillConflict.id)}
            >
              {switchCopy(saving ? "submit.pendingLabel" : "submit.label")}
            </Button>
          </Modal.Footer>
        </>
      ) : preview ? (
        <SkillPreviewContent
          skillId={preview.id}
          fallbackTitle={preview.name}
          unavailableReason={preview.unavailable_reason}
          closeLabel={actions("mcpSetup.back")}
          onClose={() => setPreview(null)}
        />
      ) : (
        <>
          <Modal.Header
            icon={icon}
            title={confirming ? t("detail.disconnectTitle", { name }) : name}
            description={
              confirming ? t("detail.disconnectDescription") : description
            }
            onClose={close}
            gap={!confirming ? 1 : undefined}
          />
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
              <>
                <MemberDetailTabs
                  enabled={hasTabs}
                  secondaryTab={
                    plugin.kind === "external-app" ? "skills" : "tools"
                  }
                  tab={activeTab}
                  onTabChange={(next) => {
                    if (!pending) {
                      setTab(next);
                    }
                  }}
                  availableActions={
                    showApprovals ? (
                      <div className="flex flex-col gap-4">
                        {policyApp ? (
                          <MemberMCPToolsList
                            tools={policyApp.actions
                              .filter(
                                (item) => item.effective_policy !== "DENY"
                              )
                              .map((item) => ({
                                id: item.action_id,
                                name: item.normalised_name,
                                display_name: item.normalised_name,
                                description: item.description,
                              }))}
                          />
                        ) : (
                          policyLoadState
                        )}
                      </div>
                    ) : undefined
                  }
                  approvalsLoading={!policyApp && !policyLoadError}
                  approvals={
                    showApprovals ? (
                      <div className="flex flex-col gap-4">
                        {policyApp ? (
                          <PolicyEditor
                            showTitle={false}
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
                              saving || !policyApp.users_can_manage_policies
                            }
                          />
                        ) : (
                          policyLoadState
                        )}
                      </div>
                    ) : undefined
                  }
                  connection={
                    <>
                      <Card border="solid" padding={4}>
                        <div className="flex items-center justify-between gap-4">
                          <div
                            role="status"
                            className="flex min-w-0 flex-1 items-center gap-3"
                          >
                            <span
                              aria-hidden
                              className={cn(
                                "size-2 shrink-0 rounded-full",
                                connection.kind === "connected"
                                  ? "bg-status-success-05"
                                  : canConnect ||
                                      connection.kind === "unconfigured"
                                    ? "bg-status-warning-05"
                                    : "bg-text-03"
                              )}
                            />
                            <div className="flex min-w-0 flex-col gap-1">
                              <Text font="main-ui-action">
                                {connectionTitle}
                              </Text>
                              {connection.kind === "connected" && (
                                <Text font="secondary-body" color="text-03">
                                  {t("detail.readyDescription")}
                                </Text>
                              )}
                              {connection.kind === "connected" &&
                                (connection.ownership === "workspace" ||
                                  connection.ownership === "session") && (
                                  <Text font="secondary-body" color="text-03">
                                    {connectionLabel}
                                  </Text>
                                )}
                            </div>
                          </div>
                          {canDisconnect && (
                            <Button
                              prominence="secondary"
                              disabled={pending}
                              onClick={() =>
                                guard.requestLeave(() =>
                                  setAction({ kind: "confirmDisconnect" })
                                )
                              }
                            >
                              {t("detail.disconnect")}
                            </Button>
                          )}
                          {canConnect && (
                            <Button
                              disabled={pending}
                              onClick={() => guard.requestLeave(onConnect)}
                            >
                              {t("connection.connect")}
                            </Button>
                          )}
                        </div>
                      </Card>
                      {plugin.kind !== "external-app" &&
                        (surface !== "craft" ||
                          (plugin.kind === "mcp" && craftEnabled)) && (
                          <Divider
                            paddingParallel={0}
                            paddingPerpendicular={0}
                          />
                        )}
                      {plugin.kind === "mcp" && (
                        <MemberMCPPreferences
                          server={plugin.server}
                          surface={surface}
                          values={preferences}
                          onChange={(changes) =>
                            setPreferences((current) => ({
                              ...current,
                              ...changes,
                            }))
                          }
                          disabled={pending}
                        />
                      )}
                      {plugin.kind === "openapi" && (
                        <>
                          {surface !== "craft" && (
                            <MemberOpenAPIPreferences
                              tool={openAPITool ?? plugin.tool}
                              values={preferences}
                              onChange={(changes) =>
                                setPreferences((current) => ({
                                  ...current,
                                  ...changes,
                                }))
                              }
                              disabled={pending}
                            />
                          )}
                        </>
                      )}
                      {plugin.kind === "external-app" &&
                        craftEnabled &&
                        connection.kind === "connected" && (
                          <ExternalAppSkillRecovery
                            appId={plugin.app.id}
                            onReview={() => setTab("skills")}
                          />
                        )}
                    </>
                  }
                  capabilities={
                    hasTabs &&
                    (surface !== "craft" || plugin.kind === "external-app") &&
                    (plugin.kind === "external-app" ? (
                      <MemberCraftAppSkills
                        appId={plugin.app.id}
                        onPreview={setPreview}
                        changes={skillChanges}
                        onChange={changeSkill}
                        disabled={pending}
                      />
                    ) : plugin.kind === "mcp" ? (
                      <MemberMCPToolsList tools={plugin.tools} />
                    ) : (
                      <div className="flex flex-col gap-4">
                        <InputTypeIn
                          searchIcon
                          value={endpointSearch}
                          onChange={(event) =>
                            setEndpointSearch(event.target.value)
                          }
                          placeholder={actions("mcpTools.search")}
                          aria-label={actions("mcpTools.search")}
                        />

                        <Text font="secondary-body" color="text-03">
                          {t("detail.toolCount", {
                            count: visibleEndpoints.length,
                          })}
                        </Text>

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
                {saveError && (
                  <Text role="alert" color="status-error-05">
                    {saveError}
                  </Text>
                )}
              </>
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
                {plugin.kind === "external-app" &&
                  craftEnabled &&
                  activeTab === "skills" && (
                    <div className="flex flex-1">
                      <Button
                        prominence="tertiary"
                        href={`/craft/v1/skills?externalAppId=${plugin.app.id}`}
                        onClick={(event) => {
                          event.preventDefault();
                          reviewSkills();
                        }}
                      >
                        {craftCopy("reviewSkillsButton")}
                      </Button>
                    </div>
                  )}
                <Button
                  prominence="secondary"
                  disabled={pending}
                  onClick={close}
                >
                  {t("detail.cancel")}
                </Button>
                <Button
                  disabled={
                    pending ||
                    !dirty ||
                    (policiesDirty && !policyApp?.users_can_manage_policies)
                  }
                  onClick={() => void saveChanges()}
                >
                  {approvalCopy("save")}
                </Button>
              </>
            )}
          </Modal.Footer>
        </>
      )}
    </PluginModalContent>
  );
}
