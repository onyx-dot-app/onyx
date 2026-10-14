"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import isEqual from "lodash/isEqual";
import { Button, InputTypeIn, MessageCard, Tabs, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgRefreshCw } from "@opal/icons";
import { useSettings } from "@/lib/settings/hooks";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { can } from "@/lib/permissions/resource-actions";
import { MCPServerStatus, type MCPServer } from "@/lib/mcp/types";
import { refreshMCPServerTools, updateMCPServer } from "@/lib/mcp/svc";
import { updateToolsStatus } from "@/lib/tools/svc";
import type { ToolSnapshot } from "@/lib/tools/types";
import type { EndpointPolicy } from "@/app/craft/v1/apps/registry";
import ToolsList from "@/sections/actions/ToolsList";
import ToolItem from "@/sections/actions/ToolItem";
import PolicyEditor from "@/sections/actions/PolicyEditor";

interface MCPServerToolsEditorProps {
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
}: MCPServerToolsEditorProps) {
  const t = useTranslations("actions");
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
      (!onlyEnabled || isEnabled(tool)) &&
      `${tool.display_name} ${tool.name} ${tool.description}`
        .toLowerCase()
        .includes(search.trim().toLowerCase())
  );

  async function save() {
    if (busy || !dirty) return;
    setBusy(true);
    setError(null);
    try {
      // Each completed batch becomes the baseline even if a later request fails.
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

  return (
    <>
      <Section padding={0} gap={4} alignItems="stretch">
        {loadError && (
          <MessageCard
            variant="error"
            title={t("mcpTools.loadError")}
            description={loadError.message}
          />
        )}
        <fieldset disabled={busy} className="flex min-w-0 flex-col gap-4">
          <Tabs defaultValue="enabled" variant="underline">
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
            <Tabs.Content value="enabled">
              <div className="flex flex-col gap-4 pt-4">
                <Text font="secondary-body" color="text-03">
                  {t("mcpTools.enabledDescription")}
                </Text>
                <InputTypeIn
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder={t("mcpTools.search")}
                  aria-label={t("mcpTools.search")}
                />
                <ToolsList
                  className="max-h-none overflow-visible"
                  isFetching={isLoading}
                  totalCount={tools.length}
                  enabledCount={tools.filter(isEnabled).length}
                  showOnlyEnabled={onlyEnabled}
                  onToggleShowOnlyEnabled={() =>
                    setOnlyEnabled((value) => !value)
                  }
                  isEmpty={visibleTools.length === 0}
                  searchQuery={search}
                  onUpdateToolsStatus={
                    tools.length > 0 &&
                    tools.every((tool) => can(tool, "toggle"))
                      ? (enabled) =>
                          setEnabledDraft(
                            Object.fromEntries(
                              tools.map((tool) => [tool.id, enabled])
                            )
                          )
                      : undefined
                  }
                >
                  {visibleTools.map((tool) => (
                    <ToolItem
                      key={tool.id}
                      name={tool.display_name || tool.name}
                      description={tool.description}
                      isEnabled={isEnabled(tool)}
                      canToggle={can(tool, "toggle")}
                      onToggle={(enabled) =>
                        setEnabledDraft((current) => ({
                          ...current,
                          [tool.id]: enabled,
                        }))
                      }
                      variant="mcp"
                    />
                  ))}
                </ToolsList>
              </div>
            </Tabs.Content>
            {craftAvailable && (
              <Tabs.Content value="policies">
                <fieldset
                  disabled={!can(server, "edit")}
                  className="min-w-0 pt-4"
                >
                  {isLoading ? (
                    <Text font="secondary-body" color="text-03">
                      {policyEditorText("loading.label")}
                    </Text>
                  ) : tools.filter(isEnabled).length ? (
                    <PolicyEditor
                      items={tools.filter(isEnabled).map((tool) => ({
                        id: tool.name,
                        name: tool.display_name || tool.name,
                        description: tool.description,
                        defaultPolicy: "ASK",
                      }))}
                      policies={policies}
                      onChange={setPolicies}
                    />
                  ) : (
                    <Text font="secondary-body" color="text-03">
                      {policyText("emptyPolicies")}
                    </Text>
                  )}
                </fieldset>
              </Tabs.Content>
            )}
          </Tabs>
        </fieldset>
        {error && (
          <MessageCard
            variant="error"
            title={t("mcpTools.saveError")}
            description={error}
          />
        )}
      </Section>
      <div className="flex flex-wrap justify-end gap-2 border-t border-border-01 pt-4">
        {can(server, "manage_status") && (
          <Button
            prominence="secondary"
            icon={SvgRefreshCw}
            disabled={
              dirty ||
              busy ||
              isLoading ||
              server.status === MCPServerStatus.FETCHING_TOOLS
            }
            onClick={refresh}
          >
            {t("mcpTools.refresh")}
          </Button>
        )}
        <Button
          disabled={!dirty || busy || isLoading || Boolean(loadError)}
          onClick={save}
        >
          {t("addMcpModal.submitButton.saveLabel")}
        </Button>
      </div>
    </>
  );
}
