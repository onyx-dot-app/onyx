"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import isEqual from "lodash/isEqual";
import {
  Button,
  InputSwitch,
  InputSingleSelect,
  InputTypeIn,
  MessageCard,
  Tabs,
  Text,
} from "@opal/components";
import { Section } from "@opal/layouts";
import MCPToolRow from "@/sections/plugins/MCPToolRow";
import { SvgRefreshCw } from "@opal/icons";
import { cn, richNodes } from "@opal/utils";
import { IconLoader } from "@opal/loaders";
import { useSettings } from "@/lib/settings/hooks";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { can } from "@/lib/permissions/resource-actions";
import { MCPServerStatus, type MCPServer } from "@/lib/mcp/types";
import { refreshMCPServerTools, updateMCPServer } from "@/lib/mcp/svc";
import { updateToolsStatus } from "@/lib/tools/svc";
import type { ToolSnapshot } from "@/lib/tools/types";
import type { EndpointPolicy } from "@/app/craft/v1/apps/registry";
import PolicyToggle from "@/sections/actions/PolicyToggle";

interface MCPServerToolsEditorProps {
  active?: boolean;
  footerTarget?: HTMLDivElement | null;
  server: MCPServer;
  onDirtyChange: (dirty: boolean) => void;
  onBusyChange: (busy: boolean) => void;
  onSaved: () => Promise<void>;
}

export default function MCPServerToolsEditor({
  server,
  onDirtyChange,
  onBusyChange,
  onSaved,
  active = true,
  footerTarget = null,
}: MCPServerToolsEditorProps) {
  const t = useTranslations("actions");
  const commonCopy = useTranslations("common");
  const policyText = useTranslations("craft.apps.mcpPolicy");
  const policyEditorText = useTranslations("craft.apps.policyEditor");
  const settings = useSettings();
  const craftAvailable = settings.onyx_craft_available === true;
  const {
    data: tools = [],
    error: loadError,
    isLoading,
    mutate,
  } = useSWR<ToolSnapshot[], Error>(
    SWR_KEYS.adminMcpServerToolSnapshots(server.id),
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      refreshInterval:
        server.status === MCPServerStatus.FETCHING_TOOLS ? 1000 : 0,
    }
  );
  const [enabledDraft, setEnabledDraft] = useState<Record<number, boolean>>({});
  const [policies, setPolicies] = useState<Record<string, EndpointPolicy>>({
    ...server.tool_policies,
  });
  const [savedPolicies, setSavedPolicies] = useState(policies);
  const [search, setSearch] = useState("");
  const [onlyEnabled, setOnlyEnabled] = useState(false);
  const [policiesView, setPoliciesView] = useState(false);
  const showPolicies = craftAvailable && policiesView;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const changedTools = tools.filter(
    (tool) =>
      can(tool, "toggle") &&
      enabledDraft[tool.id] !== undefined &&
      enabledDraft[tool.id] !== tool.enabled
  );
  const policiesDirty =
    craftAvailable && can(server, "edit") && !isEqual(policies, savedPolicies);
  const dirty = changedTools.length > 0 || policiesDirty;
  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => {
    onBusyChange(busy);
  }, [busy, onBusyChange]);
  const isEnabled = (tool: ToolSnapshot) =>
    enabledDraft[tool.id] ?? tool.enabled;
  const visibleTools = tools.filter(
    (tool) =>
      (!(onlyEnabled || showPolicies) || isEnabled(tool)) &&
      `${tool.display_name} ${tool.name} ${tool.description}`
        .toLowerCase()
        .includes(search.trim().toLowerCase())
  );

  async function save() {
    if (busy || !dirty) return;
    setBusy(true);
    setError(null);
    try {
      for (const enabled of [false, true]) {
        const ids = changedTools
          .filter((tool) => isEnabled(tool) === enabled)
          .map((tool) => tool.id);
        if (!ids.length) continue;
        await updateToolsStatus(ids, enabled);
        await mutate(
          (current) =>
            current?.map((tool) =>
              ids.includes(tool.id) ? { ...tool, enabled } : tool
            ),
          { revalidate: false }
        );
        setEnabledDraft((current) =>
          Object.fromEntries(
            Object.entries(current).filter(([id]) => !ids.includes(Number(id)))
          )
        );
      }
      if (policiesDirty) {
        const toolNames = new Set(tools.map((tool) => tool.name));
        const currentPolicies = Object.fromEntries(
          Object.entries(policies).filter(([name]) => toolNames.has(name))
        );
        await updateMCPServer(server.id, { tool_policies: currentPolicies });
        setPolicies(currentPolicies);
        setSavedPolicies(currentPolicies);
      }
      await onSaved();
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : t("mcpTools.saveError")
      );
    } finally {
      setBusy(false);
    }
  }

  async function refresh() {
    if (busy || dirty || !can(server, "manage_status")) return;
    setBusy(true);
    setError(null);
    try {
      const freshTools = await refreshMCPServerTools(server.id);
      await mutate(freshTools, { revalidate: false });
      setEnabledDraft({});
      await onSaved();
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : t("mcpTools.refreshError")
      );
    } finally {
      setBusy(false);
    }
  }

  const enabledCount = tools.filter(isEnabled).length;
  const enabledTools = tools.filter(isEnabled);
  const effectivePolicies = enabledTools.map(
    (tool) => policies[tool.name] ?? "ASK"
  );
  const bulkPolicy =
    effectivePolicies.every((policy) => policy === "ALWAYS") &&
    effectivePolicies.length > 0
      ? "ALWAYS"
      : effectivePolicies.every((policy) => policy === "ASK")
        ? "ASK"
        : "CUSTOM";
  const policyDisabled = busy || Boolean(loadError) || !can(server, "edit");
  const canBulkToggle =
    tools.length > 0 && tools.every((tool) => can(tool, "toggle"));
  const toolsContent = (
    <div className="flex h-[min(24rem,45dvh)] flex-col gap-3">
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <div className="flex-1 min-w-40">
          <InputTypeIn
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("mcpTools.search")}
            aria-label={t("mcpTools.search")}
          />
        </div>
        {can(server, "manage_status") && (
          <Button
            prominence="secondary"
            icon={SvgRefreshCw}
            disabled={
              dirty ||
              busy ||
              isLoading ||
              server.status === MCPServerStatus.FETCHING_TOOLS ||
              Boolean(loadError)
            }
            onClick={refresh}
          >
            {t("mcpTools.refresh")}
          </Button>
        )}
      </div>
      {!isLoading && tools.length > 0 && (
        <div className="grid shrink-0 grid-cols-1 items-center gap-2 sm:grid-cols-[minmax(0,1fr)_18rem]">
          <div className="flex min-h-10 flex-wrap items-center gap-4">
            <Text font="secondary-body" color="text-03">
              {richNodes(
                commonCopy.rich("enabledCount.label", {
                  enabled: enabledCount,
                  total: tools.length,
                  value: (chunks) => chunks,
                })
              )}
            </Text>
            <label
              aria-hidden={showPolicies}
              className={cn(
                "flex items-center gap-2",
                showPolicies && "invisible"
              )}
            >
              <InputSwitch
                checked={onlyEnabled}
                onCheckedChange={setOnlyEnabled}
                disabled={busy || showPolicies}
                aria-label={t("toolsList.showEnabledButton.ariaLabel")}
              />
              <Text font="secondary-body" color="text-03">
                {t("toolsList.showEnabledButton.tooltip")}
              </Text>
            </label>
          </div>
          <div className="flex min-h-10 items-center justify-end">
            {showPolicies ? (
              <div className="flex items-center gap-2">
                <Text font="secondary-body" color="text-03">
                  {policyEditorText("permissions.title")}
                </Text>
                <div className="w-44">
                  <InputSingleSelect
                    aria-label={policyEditorText("permissions.title")}
                    disabled={policyDisabled || enabledCount === 0}
                    value={bulkPolicy === "CUSTOM" ? "" : bulkPolicy}
                    defaultOption={
                      bulkPolicy === "CUSTOM" ? undefined : bulkPolicy
                    }
                    placeholder={policyEditorText("permissions.customOption")}
                    options={[
                      {
                        value: "ALWAYS",
                        title: policyEditorText(
                          "permissions.autoApproveOption"
                        ),
                      },
                      {
                        value: "ASK",
                        title: policyEditorText("permissions.askOption"),
                      },
                    ]}
                    onValueChange={(value) => {
                      if (value !== "ALWAYS" && value !== "ASK") return;
                      setPolicies((current) => ({
                        ...current,
                        ...Object.fromEntries(
                          enabledTools.map((tool) => [tool.name, value])
                        ),
                      }));
                    }}
                  />
                </div>
              </div>
            ) : (
              canBulkToggle && (
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    prominence="tertiary"
                    disabled={
                      busy ||
                      Boolean(loadError) ||
                      enabledCount === tools.length
                    }
                    onClick={() =>
                      setEnabledDraft(
                        Object.fromEntries(tools.map((tool) => [tool.id, true]))
                      )
                    }
                  >
                    {t("toolsList.enableAllButton.label")}
                  </Button>
                  <Button
                    size="sm"
                    prominence="tertiary"
                    disabled={busy || Boolean(loadError) || enabledCount === 0}
                    onClick={() =>
                      setEnabledDraft(
                        Object.fromEntries(
                          tools.map((tool) => [tool.id, false])
                        )
                      )
                    }
                  >
                    {t("toolsList.disableAllButton.ariaLabel")}
                  </Button>
                </div>
              )
            )}
          </div>
        </div>
      )}
      <div
        role="region"
        aria-label={t("mcpTools.title")}
        className="min-h-0 flex-1 overflow-y-auto"
      >
        {isLoading ? (
          <Section flexDirection="row" gap={2} padding={4} height="auto">
            <IconLoader />
            <Text font="secondary-body" color="text-03">
              {policyEditorText("loading.label")}
            </Text>
          </Section>
        ) : visibleTools.length === 0 ? (
          <Section padding={6} height="auto">
            <Text font="secondary-body" color="text-03">
              {showPolicies && enabledCount === 0 && !search.trim()
                ? policyText("emptyPolicies")
                : t(
                    search.trim()
                      ? "toolsList.empty.searchMessage"
                      : "toolsList.empty.message"
                  )}
            </Text>
          </Section>
        ) : (
          <ul className="m-0 list-none divide-y divide-border-01 rounded-12 border border-border-01 p-0">
            {visibleTools.map((tool) => (
              <MCPToolRow
                key={tool.id}
                tool={tool}
                control={
                  showPolicies ? (
                    <PolicyToggle
                      value={policies[tool.name] ?? "ASK"}
                      disabled={policyDisabled}
                      onChange={(value) =>
                        setPolicies((current) => ({
                          ...current,
                          [tool.name]: value,
                        }))
                      }
                    />
                  ) : (
                    <InputSwitch
                      checked={isEnabled(tool)}
                      disabled={
                        busy || Boolean(loadError) || !can(tool, "toggle")
                      }
                      aria-label={`tool-toggle-${tool.display_name || tool.name}`}
                      onCheckedChange={(enabled) =>
                        setEnabledDraft((current) => ({
                          ...current,
                          [tool.id]: enabled,
                        }))
                      }
                    />
                  )
                }
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );

  return (
    <Section padding={0} gap={4} alignItems="stretch" height="auto">
      <Section padding={0} gap={4} alignItems="stretch">
        {loadError && (
          <MessageCard
            variant="error"
            title={t("mcpTools.loadError")}
            description={loadError.message}
          />
        )}
        <fieldset disabled={busy} className="flex min-w-0 flex-col gap-4">
          {craftAvailable ? (
            <Tabs
              value={showPolicies ? "policies" : "enabled"}
              onValueChange={(value) => setPoliciesView(value === "policies")}
              variant="underline"
              gap={4}
            >
              <Tabs.List>
                <Tabs.Trigger value="enabled">
                  {t("mcpTools.enabledTab")}
                </Tabs.Trigger>
                {craftAvailable && (
                  <Tabs.Trigger value="policies">
                    {t("mcpTools.policiesTab")}
                  </Tabs.Trigger>
                )}
              </Tabs.List>
              <Tabs.Content value={showPolicies ? "policies" : "enabled"}>
                {toolsContent}
              </Tabs.Content>
            </Tabs>
          ) : (
            toolsContent
          )}
        </fieldset>
        {error && (
          <MessageCard
            variant="error"
            title={t("mcpTools.saveError")}
            description={error}
          />
        )}
      </Section>
      {active &&
        (footerTarget ? (
          createPortal(
            <Button
              disabled={!dirty || busy || isLoading || Boolean(loadError)}
              onClick={save}
            >
              {t("addMcpModal.submitButton.saveLabel")}
            </Button>,
            footerTarget
          )
        ) : (
          <div className="flex flex-wrap justify-end gap-2 border-t border-border-01 pt-4">
            <Button
              disabled={!dirty || busy || isLoading || Boolean(loadError)}
              onClick={save}
            >
              {t("addMcpModal.submitButton.saveLabel")}
            </Button>
          </div>
        ))}
    </Section>
  );
}
