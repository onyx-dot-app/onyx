"use client";

import { useState, useEffect, useCallback } from "react";
import { useTranslations } from "next-intl";
import { useFocusOnMount } from "@opal/hooks";
import {
  InputTypeIn,
  Button,
  LineItemButton,
  Popover,
  PopoverMenu,
} from "@opal/components";
import { SvgActions, SvgKey, SvgSliders, SvgSimpleLoader } from "@opal/icons";

import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { MinimalAgent } from "@/lib/agents/types";
import MCPApiKeyModal from "@/components/chat/MCPApiKeyModal";
import useCCPairs from "@/hooks/useCCPairs";
import { useLLMProviders } from "@/lib/languageModels/hooks";
import { hasPermission } from "@/lib/permissions";
import { useProjectsContext } from "@/lib/projects/providers";
import { useSettings } from "@/lib/settings/hooks";
import { FILE_READER_TOOL_ID, SEARCH_TOOL_ID } from "@/lib/tools/constants";
import {
  useBuiltInToolNames,
  type ToolConfigurationHandle,
} from "@/lib/tools/hooks";
import { ToolsPopoverProvider } from "@/lib/tools/providers";
import MCPLineItem, { MCPServer } from "@/lib/tools/components/MCPLineItem";
import SourcesView from "@/lib/tools/components/SourcesView";
import SwitchList, { SwitchListItem } from "@/lib/tools/components/SwitchList";
import ToolLineItem from "@/lib/tools/components/ToolLineItem";
import {
  MCPAuthenticationType,
  MCPAuthenticationPerformer,
  SecondaryViewState,
} from "@/lib/tools/types";
import { Permission } from "@/lib/types";
import {
  getMCPUserOAuthNavigationUrl,
  saveMCPUserCredentials,
  startMCPUserOAuth,
} from "@/lib/tools/svc";
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
  const [mcpServers, setMcpServers] = useState<MCPServer[]>([]);
  const { llmProviders, isLoading: isLLMLoading } = useLLMProviders(agent.id);
  const hasAnyProvider = !isLLMLoading && (llmProviders?.length ?? 0) > 0;

  // Store MCP server auth/loading state (tools are part of agent.tools)
  const [mcpServerData, setMcpServerData] = useState<{
    [serverId: number]: {
      isAuthenticated: boolean;
      isLoading: boolean;
    };
  }>({});

  const [mcpApiKeyModal, setMcpApiKeyModal] = useState<{
    isOpen: boolean;
    serverId: number | null;
    serverName: string;
    authTemplate?: any;
    onSuccess?: () => void;
    isAuthenticated?: boolean;
    existingCredentials?: Record<string, string>;
  }>({
    isOpen: false,
    serverId: null,
    serverName: "",
    authTemplate: undefined,
    onSuccess: undefined,
    isAuthenticated: false,
  });

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

  // Fetch MCP servers for the agent on mount
  useEffect(() => {
    if (agent == null || agent.id == null || !hasAnyProvider) return;

    const abortController = new AbortController();

    const fetchMCPServers = async () => {
      try {
        const response = await fetch(`/api/mcp/servers/persona/${agent.id}`, {
          signal: abortController.signal,
        });
        if (response.ok) {
          const data = await response.json();
          const servers = data.mcp_servers || [];
          setMcpServers(servers);
          // Seed auth/loading state based on response
          setMcpServerData((prev) => {
            const next = { ...prev } as any;
            servers.forEach((s: any) => {
              next[s.id as number] = {
                isAuthenticated: !!s.user_can_authenticate,
                isLoading: false,
              };
            });
            return next;
          });
        }
      } catch (error) {
        if (abortController.signal.aborted) {
          return;
        }
        console.error("Error fetching MCP servers:", error);
      }
    };

    fetchMCPServers();

    return () => {
      abortController.abort();
    };
  }, [agent?.id, hasAnyProvider]);

  // Handle MCP authentication
  const handleMCPAuthenticate = async (
    serverId: number,
    authType: MCPAuthenticationType,
    forceReauthentication = false
  ) => {
    if (authType === MCPAuthenticationType.OAUTH) {
      const updateLoadingState = (loading: boolean) => {
        setMcpServerData((prev) => {
          const previous = prev[serverId] ?? {
            isAuthenticated: false,
            isLoading: false,
          };
          return {
            ...prev,
            [serverId]: {
              ...previous,
              isLoading: loading,
            },
          };
        });
      };

      updateLoadingState(true);
      try {
        const oauthStart = await startMCPUserOAuth(
          serverId,
          window.location.pathname + window.location.search,
          { forceReauthentication }
        );
        window.location.href = getMCPUserOAuthNavigationUrl(oauthStart);
      } catch (error) {
        console.error("Error initiating OAuth:", error);
        updateLoadingState(false);
        throw error;
      }
    }
  };

  // Both submit paths are the same request; the API-key form just names its
  // one field. `saveMCPUserCredentials` owns the endpoint and its errors.
  const handleMCPApiKeySubmit = (serverId: number, apiKey: string) =>
    saveMCPUserCredentials(serverId, { api_key: apiKey });

  const handleMCPCredentialsSubmit = (
    serverId: number,
    credentials: Record<string, string>
  ) => saveMCPUserCredentials(serverId, credentials);

  const handleServerAuthentication = (
    server: MCPServer,
    forceReauthentication = false
  ) => {
    const authType = server.auth_type;
    const performer = server.auth_performer;
    const requiresHeaderValues =
      (server.auth_template?.required_fields.length ?? 0) > 0;

    if (!requiresHeaderValues && authType === MCPAuthenticationType.OAUTH) {
      void handleMCPAuthenticate(
        server.id,
        MCPAuthenticationType.OAUTH,
        forceReauthentication
      ).catch(() => undefined);
      return;
    }
    if (
      !requiresHeaderValues &&
      (authType === MCPAuthenticationType.NONE ||
        performer === MCPAuthenticationPerformer.ADMIN)
    ) {
      return;
    }
    if (requiresHeaderValues || authType === MCPAuthenticationType.API_TOKEN) {
      setMcpApiKeyModal({
        isOpen: true,
        serverId: server.id,
        serverName: server.name,
        authTemplate: server.auth_template,
        onSuccess: async () => {
          if (authType === MCPAuthenticationType.OAUTH) {
            await handleMCPAuthenticate(
              server.id,
              MCPAuthenticationType.OAUTH,
              forceReauthentication
            );
            return;
          }
          // Update the authentication state after successful credential submission
          setMcpServerData((prev) => ({
            ...prev,
            [server.id]: {
              ...prev[server.id],
              isAuthenticated: true,
              isLoading: false,
            },
          }));
        },
        isAuthenticated: server.user_can_authenticate,
        existingCredentials: server.user_credentials,
      });
    }
  };

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
  const selectedMcpServerData = selectedMcpServer
    ? mcpServerData[selectedMcpServer.id]
    : undefined;
  const isActiveServerAuthenticated =
    selectedMcpServerData?.isAuthenticated ??
    !!selectedMcpServer?.user_can_authenticate;
  const showActiveReauthRow =
    !!selectedMcpServer &&
    selectedMcpTools.length > 0 &&
    selectedMcpServer.auth_performer === MCPAuthenticationPerformer.PER_USER &&
    selectedMcpServer.auth_type !== MCPAuthenticationType.NONE &&
    isActiveServerAuthenticated;

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
      disabled={selectedMcpServerData?.isLoading}
      onClick={handleFooterReauthClick}
      icon={selectedMcpServerData?.isLoading ? SvgSimpleLoader : SvgKey}
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
          const serverData = mcpServerData[server.id] || {
            isAuthenticated: !!server.user_can_authenticate,
            isLoading: false,
          };

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
              isAuthenticated={serverData.isAuthenticated}
              isLoading={serverData.isLoading}
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

      {/* MCP API Key Modal */}
      {mcpApiKeyModal.isOpen && (
        <MCPApiKeyModal
          isOpen={mcpApiKeyModal.isOpen}
          onClose={() =>
            setMcpApiKeyModal({
              isOpen: false,
              serverId: null,
              serverName: "",
              authTemplate: undefined,
              onSuccess: undefined,
              isAuthenticated: false,
              existingCredentials: undefined,
            })
          }
          serverName={mcpApiKeyModal.serverName}
          serverId={mcpApiKeyModal.serverId ?? 0}
          authTemplate={mcpApiKeyModal.authTemplate}
          onSubmit={handleMCPApiKeySubmit}
          onSubmitCredentials={handleMCPCredentialsSubmit}
          onSuccess={mcpApiKeyModal.onSuccess}
          isAuthenticated={mcpApiKeyModal.isAuthenticated}
          existingCredentials={mcpApiKeyModal.existingCredentials}
        />
      )}
    </ToolsPopoverProvider>
  );
}
