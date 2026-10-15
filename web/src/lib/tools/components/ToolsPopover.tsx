"use client";

import { IconLoader } from "@opal/loaders";
import { useState, useCallback, useEffect } from "react";
import { useTranslations } from "next-intl";
import { useFocusOnMount } from "@opal/hooks";
import {
  InputTypeIn,
  Button,
  LineItemButton,
  Popover,
  PopoverMenu,
} from "@opal/components";
import { SvgActions, SvgKey, SvgSliders } from "@opal/icons";

import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { MinimalAgent } from "@/lib/agents/types";
import MCPUserCredentialsModal from "@/lib/mcp/components/MCPUserCredentialsModal";
import { useMcpAuthentication } from "@/lib/mcp/hooks";
import { canAuthenticateMcpServer } from "@/lib/mcp/auth";
import { toast } from "@opal/layouts";
import useCCPairs from "@/hooks/useCCPairs";
import { useLanguageModelsForAgent } from "@/lib/languageModels/hooks";
import { hasPermission } from "@/lib/permissions/utils";
import { useProjectsContext } from "@/lib/projects/providers";
import { useSettings } from "@/lib/settings/hooks";
import { FILE_READER_TOOL_ID, SEARCH_TOOL_ID } from "@/lib/tools/constants";
import {
  useBuiltInToolNames,
  type ToolConfigurationHandle,
} from "@/lib/tools/hooks";
import { ToolsPopoverProvider } from "@/lib/tools/providers";
import { MCPLineItem } from "@/lib/mcp/components";
import SourcesView from "@/lib/tools/components/SourcesView";
import SwitchList, { SwitchListItem } from "@/lib/tools/components/SwitchList";
import ToolLineItem from "@/lib/tools/components/ToolLineItem";
import { SecondaryViewState } from "@/lib/tools/types";
import { Permission } from "@/lib/types";
import { useUser } from "@/providers/UserProvider";

/**
 * The actions popover.
 *
 * Takes the agent rather than resolving one. Everything the panel shows is
 * scoped to it — the rows are its tools, the toggles are its per-agent
 * preferences, the sources are what it can reach — so the caller decides
 * which agent this acts on, and the panel never has to ask whether it has one.
 *
 * Callers should key this on the agent, so switching starts clean rather than
 * carrying the previous agent's open panel and search term across.
 */
export interface ToolsPopoverProps {
  agent: MinimalAgent;
  /**
   * Owned by the surface, because the send path reads the same one. The
   * popover decides nothing about where it lives or how long it lasts.
   */
  toolConfiguration: ToolConfigurationHandle;
  disabled?: boolean;
}

export default function ToolsPopover({
  agent,
  toolConfiguration,
  disabled = false,
}: ToolsPopoverProps) {
  const t = useTranslations("actions");
  const builtInToolNames = useBuiltInToolNames();
  const [open, setOpen] = useState(false);
  const [secondaryView, setSecondaryView] = useState<SecondaryViewState | null>(
    null
  );
  const [searchTerm, setSearchTerm] = useState("");
  const focusOnMount = useFocusOnMount<HTMLInputElement>();
  const { llmProviders, isLoading: isLLMLoading } = useLanguageModelsForAgent(
    agent.id
  );
  const hasAnyProvider = !isLLMLoading && (llmProviders?.length ?? 0) > 0;

  const {
    servers: mcpServers,
    authenticate: handleServerAuthentication,
    loadingServerId,
    authenticationError,
    credentialRequest,
    cancelCredentialRequest,
    submitCredentials,
  } = useMcpAuthentication(agent.id, hasAnyProvider);

  useEffect(() => {
    if (authenticationError) toast.error(authenticationError.message);
  }, [authenticationError]);

  const { permissions } = useUser();
  const { vectorDbEnabled } = useSettings();
  const { ccPairs } = useCCPairs(vectorDbEnabled);
  const { currentProjectId, allCurrentProjectFiles } = useProjectsContext();

  // Check if there are any connectors available
  const hasNoConnectors = ccPairs.length === 0;

  const close = useCallback(() => setOpen(false), []);
  const openSources = useCallback(
    () => setSecondaryView({ type: "sources" }),
    []
  );

  // Filter out MCP tools from the main list (they have mcp_server_id)
  // Also filter out internal search tool for basic users when there are no connectors
  // Also filter out tools that are not chat-selectable (e.g., OpenURL)
  const displayTools = agent.tools.filter((tool) => {
    // Filter out MCP tools
    if (tool.mcp_server_id) return false;

    // Filter out tools that are not chat-selectable (visibility set by backend)
    if (!tool.chat_selectable) return false;

    // Always hide File Reader from the actions popover
    if (tool.in_code_tool_id === FILE_READER_TOOL_ID) return false;

    // Special handling for Project Search
    // Ensure Project Search is hidden if no files exist
    if (tool.in_code_tool_id === SEARCH_TOOL_ID && !!currentProjectId) {
      if (!allCurrentProjectFiles || allCurrentProjectFiles.length === 0) {
        return false;
      }
      // If files exist, show it (even if backend thinks it's strictly unavailable due to no connectors)
      return true;
    }

    // Advertise to admin/curator users that they can connect an internal search tool
    // even if it's not available or has no connectors
    if (
      tool.in_code_tool_id === SEARCH_TOOL_ID &&
      hasPermission(permissions, Permission.MANAGE_CONNECTORS)
    ) {
      return true;
    }

    // Filter out internal search tool for users without connector management when there are no connectors
    if (
      tool.in_code_tool_id === SEARCH_TOOL_ID &&
      hasNoConnectors &&
      !hasPermission(permissions, Permission.MANAGE_CONNECTORS)
    ) {
      return false;
    }

    return true;
  });

  // Filter tools based on search term
  const filteredTools = displayTools.filter((tool) => {
    if (!searchTerm) return true;
    const searchLower = searchTerm.toLowerCase();
    // Match the name the row actually shows, including the rename search
    // takes on inside a project, so typing what is on screen finds it. The
    // raw names stay searchable below for anyone who knows them.
    const shownName =
      currentProjectId != null && tool.in_code_tool_id === SEARCH_TOOL_ID
        ? t("actionLineItem.projectSearch.label")
        : (builtInToolNames[tool.in_code_tool_id ?? ""] ?? tool.display_name);
    return (
      shownName?.toLowerCase().includes(searchLower) ||
      tool.display_name?.toLowerCase().includes(searchLower) ||
      tool.name.toLowerCase().includes(searchLower) ||
      tool.description?.toLowerCase().includes(searchLower)
    );
  });

  // Filter MCP servers based on search term
  const filteredMCPServers = mcpServers.filter((server) => {
    if (!searchTerm) return true;
    const searchLower = searchTerm.toLowerCase();
    return server.name.toLowerCase().includes(searchLower);
  });

  const selectedMcpServerId =
    secondaryView?.type === "mcp" ? secondaryView.serverId : null;
  const selectedMcpServer = selectedMcpServerId
    ? mcpServers.find((server) => server.id === selectedMcpServerId)
    : undefined;
  const selectedMcpTools =
    selectedMcpServerId !== null
      ? agent.tools.filter(
          (t) => t.mcp_server_id === Number(selectedMcpServerId)
        )
      : [];
  const showActiveReauthRow =
    !!selectedMcpServer &&
    selectedMcpTools.length > 0 &&
    canAuthenticateMcpServer(selectedMcpServer) &&
    selectedMcpServer.user_can_authenticate === true;

  const mcpToggleItems: SwitchListItem[] = selectedMcpTools.map((tool) => ({
    id: tool.id.toString(),
    label: tool.display_name || tool.name,
    description: tool.description,
    isEnabled: !toolConfiguration.disabledToolIds.includes(tool.id),
    onToggle: () => toolConfiguration.toggleToolState(tool.id, "disabled"),
  }));

  const mcpAllDisabled = selectedMcpTools.every((tool) =>
    toolConfiguration.disabledToolIds.includes(tool.id)
  );

  // One call per tool rather than a second setter taking many. React batches
  // them, and each sees what the one before it left, so the rules hold across
  // the run instead of the last write landing on a stale map.
  const setSelectedServerToolsDisabled = (disabled: boolean) => {
    if (!selectedMcpServer) return;
    for (const tool of selectedMcpTools) {
      toolConfiguration.setToolState(tool.id, () =>
        disabled ? "disabled" : null
      );
    }
  };

  const handleFooterReauthClick = () => {
    if (selectedMcpServer) {
      handleServerAuthentication(selectedMcpServer, true);
    }
  };

  const handleOpenChange = (newOpen: boolean) => {
    setOpen(newOpen);
    if (newOpen) {
      setSecondaryView(null);
      setSearchTerm("");
    }
  };

  const mcpFooter = showActiveReauthRow ? (
    <LineItemButton
      disabled={loadingServerId === selectedMcpServer?.id}
      onClick={handleFooterReauthClick}
      icon={loadingServerId === selectedMcpServer?.id ? IconLoader : SvgKey}
      title={t("toolsPopover.reauthenticate.label")}
      sizePreset="main-ui"
      variant="section"
    />
  ) : undefined;

  const primaryView = (
    <PopoverMenu>
      {[
        <InputTypeIn
          key="search"
          placeholder={t("toolsPopover.search.placeholder")}
          searchIcon
          value={searchTerm}
          onChange={(event) => setSearchTerm(event.target.value)}
          ref={focusOnMount}
          variant="internal"
        />,

        // Actions
        ...filteredTools.map((tool) => (
          <ToolLineItem key={tool.id} tool={tool} />
        )),

        // MCP Servers
        ...filteredMCPServers.map((server) => {
          // Tools for this server come from assistant.tools
          const serverTools = agent.tools.filter(
            (t) => t.mcp_server_id === Number(server.id)
          );
          const enabledTools = serverTools.filter(
            (t) => !toolConfiguration.disabledToolIds.includes(t.id)
          );

          return (
            <MCPLineItem
              key={server.id}
              server={server}
              isActive={selectedMcpServerId === server.id}
              tools={serverTools}
              enabledTools={enabledTools}
              isAuthenticated={server.user_can_authenticate === true}
              isLoading={loadingServerId === server.id}
              onSelect={() =>
                setSecondaryView({
                  type: "mcp",
                  serverId: server.id,
                })
              }
              onAuthenticate={() => handleServerAuthentication(server)}
            />
          );
        }),

        null,

        hasPermission(permissions, Permission.MANAGE_ACTIONS) && (
          <LineItemButton
            key="more-actions"
            href={ADMIN_ROUTES.MCP_ACTIONS.path}
            icon={SvgActions}
            title={t("toolsPopover.moreActions.label")}
            sizePreset="main-ui"
            variant="section"
            rounding={2}
          />
        ),
      ]}
    </PopoverMenu>
  );

  const mcpView = (
    <SwitchList
      items={mcpToggleItems}
      searchPlaceholder={t("toolsPopover.mcpTools.searchPlaceholder", {
        server:
          selectedMcpServer?.name ?? t("toolsPopover.serverFallback.label"),
      })}
      allDisabled={mcpAllDisabled}
      onDisableAll={() => setSelectedServerToolsDisabled(true)}
      onEnableAll={() => setSelectedServerToolsDisabled(false)}
      disableAllLabel={t("toolsPopover.disableAllTools.label")}
      enableAllLabel={t("toolsPopover.enableAllTools.label")}
      onBack={() => setSecondaryView(null)}
      footer={mcpFooter}
    />
  );

  // If no tools or MCP servers are available, don't render the component
  if (displayTools.length === 0 && mcpServers.length === 0) return null;

  return (
    <ToolsPopoverProvider
      agent={agent}
      toolConfiguration={toolConfiguration}
      openSources={openSources}
      close={close}
    >
      <Popover open={open} onOpenChange={handleOpenChange}>
        <Popover.Trigger asChild>
          <div data-testid="action-management-toggle">
            <Button
              disabled={disabled}
              icon={SvgSliders}
              interaction={open ? "hover" : "rest"}
              prominence="tertiary"
              tooltip={t("toolsPopover.manageActions.tooltip")}
            />
          </div>
        </Popover.Trigger>
        <Popover.Content side="bottom" align="start" width="lg">
          <div data-testid="tool-options">
            {secondaryView ? (
              secondaryView.type === "mcp" ? (
                mcpView
              ) : (
                <SourcesView onBack={() => setSecondaryView(null)} />
              )
            ) : (
              primaryView
            )}
          </div>
        </Popover.Content>
      </Popover>

      {credentialRequest && (
        <MCPUserCredentialsModal
          key={credentialRequest.server.id}
          server={credentialRequest.server}
          onClose={cancelCredentialRequest}
          onSubmit={submitCredentials}
        />
      )}
    </ToolsPopoverProvider>
  );
}
