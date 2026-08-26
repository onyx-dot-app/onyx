"use client";

import { FILE_READER_TOOL_ID, SEARCH_TOOL_ID } from "@/lib/tools/constants";
import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useFocusOnMount } from "@opal/hooks";
import { InputTypeIn, Button, Popover, PopoverMenu } from "@opal/components";
import { SvgActions, SvgKey, SvgSliders, SvgSimpleLoader } from "@opal/icons";
import SwitchList, { SwitchListItem } from "@/lib/tools/components/SwitchList";
import {
  MCPAuthenticationType,
  MCPAuthenticationPerformer,
  SecondaryViewState,
} from "@/lib/tools/types";
import { useForcedTools } from "@/lib/hooks/useForcedTools";
import { useAgentPreferences } from "@/lib/agents/hooks";
import { MinimalAgent } from "@/lib/agents/types";
import { useUser } from "@/providers/UserProvider";
import { hasPermission } from "@/lib/permissions";
import { useSourcePreferences } from "@/lib/searchFilters/hooks";
import MCPApiKeyModal from "@/components/chat/MCPApiKeyModal";
import { Permission, ValidSources } from "@/lib/types";
import { NO_DISABLED_TOOLS } from "@/lib/tools/constants";
import { getAdminConfigureInfo, getToolTooltip } from "@/lib/tools/utils";
import { getConfiguredSources } from "@/lib/sources";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { SourceMetadata } from "@/lib/search/interfaces";
import { SourceIcon } from "@/components/SourceIcon";
import { useAvailableTools } from "@/hooks/useAvailableTools";
import { useAvailableSources } from "@/lib/connectors/hooks";
import useCCPairs from "@/hooks/useCCPairs";
import { useLLMProviders } from "@/lib/languageModels/hooks";
import { useSettings } from "@/lib/settings/hooks";
import { useToolOAuthStatus } from "@/lib/hooks/useToolOAuthStatus";
import LineItem from "@/refresh-components/buttons/LineItem";
import ActionLineItem from "@/lib/tools/components/ActionLineItem";
import MCPLineItem, { MCPServer } from "@/lib/tools/components/MCPLineItem";
import { useProjectsContext } from "@/lib/projects/providers";
import { isAssistant } from "@/lib/agents/utils";
import {
  getMCPUserOAuthNavigationUrl,
  saveMCPUserCredentials,
  startMCPUserOAuth,
} from "@/lib/tools/svc";
import type { SearchFilters } from "@/lib/searchFilters/types";

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
  filterManager: SearchFilters;
  disabled?: boolean;
}

export default function ToolsPopover({
  agent,
  filterManager,
  disabled = false,
}: ToolsPopoverProps) {
  const { availableSources } = useAvailableSources();
  const [open, setOpen] = useState(false);
  const [secondaryView, setSecondaryView] = useState<SecondaryViewState | null>(
    null
  );
  const [searchTerm, setSearchTerm] = useState("");
  const focusOnMount = useFocusOnMount<HTMLInputElement>();
  // const [showFadeMask, setShowFadeMask] = useState(false);
  // const [showTopShadow, setShowTopShadow] = useState(false);
  const { selectedSources, setSelectedSources } = filterManager;
  const [mcpServers, setMcpServers] = useState<MCPServer[]>([]);
  const { llmProviders, isLoading: isLLMLoading } = useLLMProviders(agent.id);
  const hasAnyProvider = !isLLMLoading && (llmProviders?.length ?? 0) > 0;

  // Use the OAuth hook
  const { getToolAuthStatus, authenticateTool } = useToolOAuthStatus(agent.id);

  const agentIsAssistant = isAssistant(agent);

  const hasSearchTool = agent.tools.some(
    (tool) => tool.in_code_tool_id === SEARCH_TOOL_ID
  );

  // knowledge_sources from the backend is the complete set of source types this agent
  // can search over (doc sets, federated, hierarchy nodes, attached docs, user files).
  // Default agent is special-cased to show everything available.
  const agentAccessibleSources = useMemo(() => {
    if (agentIsAssistant) {
      return null; // null means "all accessible"
    }

    const sources = agent.knowledge_sources ?? [];
    if (sources.length === 0 && hasSearchTool) {
      return null;
    }

    return new Set<string>(sources);
  }, [agentIsAssistant, agent.knowledge_sources, hasSearchTool]);

  // Scope availableSources to only what this agent can access. This ensures
  // that (a) agent-only sources like user_file appear in the toggle list and
  // (b) stale sources from localStorage (e.g. Web on an agent with only Notion)
  // don't leak into selectedSources / the YQL query.
  const effectiveAvailableSources = useMemo(() => {
    if (agentAccessibleSources === null) return availableSources;
    return Array.from(agentAccessibleSources) as ValidSources[];
  }, [agentAccessibleSources, availableSources]);

  const {
    sourcesInitialized,
    enableSources,
    enableAllSources: baseEnableAllSources,
    disableAllSources: baseDisableAllSources,
    toggleSource: baseToggleSource,
    isSourceEnabled,
  } = useSourcePreferences({
    availableSources: effectiveAvailableSources,
    selectedSources,
    setSelectedSources,
  });

  // Store previously enabled sources when search tool is disabled
  const previouslyEnabledSourcesRef = useRef<SourceMetadata[]>([]);

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

  // Get the agent preference for this assistant
  const { agentPreferences, setSpecificAgentPreferences } =
    useAgentPreferences();
  const { forcedToolIds, setForcedToolIds } = useForcedTools();

  // Reset state when assistant changes
  useEffect(() => {
    setForcedToolIds([]);
  }, [agent.id, setForcedToolIds]);

  const { isAdmin, permissions } = useUser();
  const { vectorDbEnabled } = useSettings();

  const { tools: availableTools } = useAvailableTools();
  const { ccPairs } = useCCPairs(vectorDbEnabled);
  const { currentProjectId, allCurrentProjectFiles } = useProjectsContext();
  const availableToolIdSet = new Set(availableTools.map((tool) => tool.id));

  // Check if there are any connectors available
  const hasNoConnectors = ccPairs.length === 0;

  const agentPreference = agentPreferences?.[agent.id];
  const disabledToolIds =
    agentPreference?.disabled_tool_ids || NO_DISABLED_TOOLS;
  const toggleToolForCurrentAgent = useCallback(
    (toolId: number) => {
      const disabled = disabledToolIds.includes(toolId);
      setSpecificAgentPreferences(agent.id, {
        disabled_tool_ids: disabled
          ? disabledToolIds.filter((id) => id !== toolId)
          : [...disabledToolIds, toolId],
      });

      // If we're disabling a tool that is currently forced, remove it from forced tools
      if (!disabled && forcedToolIds.includes(toolId)) {
        setForcedToolIds(forcedToolIds.filter((id) => id !== toolId));
      }
    },
    [
      disabledToolIds,
      agent.id,
      setSpecificAgentPreferences,
      forcedToolIds,
      setForcedToolIds,
    ]
  );

  const toggleForcedTool = useCallback(
    (toolId: number) => {
      if (forcedToolIds.includes(toolId)) {
        // If clicking on already forced tool, unforce it
        setForcedToolIds([]);
      } else {
        // If clicking on a new tool, replace any existing forced tools with just this one
        setForcedToolIds([toolId]);
      }
    },
    [forcedToolIds, setForcedToolIds]
  );

  // Get internal search tool reference for auto-pin logic
  const internalSearchTool = useMemo(
    () =>
      agent.tools.find(
        (tool) => tool.in_code_tool_id === SEARCH_TOOL_ID && !tool.mcp_server_id
      ),
    [agent.tools]
  );

  // Handle explicit force toggle from ActionLineItem
  const handleForceToggleWithTracking = useCallback(
    (toolId: number, wasForced: boolean) => {
      if (
        !wasForced &&
        internalSearchTool &&
        toolId === internalSearchTool.id
      ) {
        setSelectedSources(getConfiguredSources(effectiveAvailableSources));
      }
      toggleForcedTool(toolId);
    },
    [
      toggleForcedTool,
      internalSearchTool,
      effectiveAvailableSources,
      setSelectedSources,
    ]
  );

  const enableAllSources = useCallback(() => {
    setSelectedSources(getConfiguredSources(effectiveAvailableSources));

    if (internalSearchTool) {
      setForcedToolIds([internalSearchTool.id]);
    }
  }, [
    effectiveAvailableSources,
    setSelectedSources,
    internalSearchTool,
    setForcedToolIds,
  ]);

  const disableAllSources = useCallback(() => {
    baseDisableAllSources();
    const willUnpin =
      internalSearchTool && forcedToolIds.includes(internalSearchTool.id);
    if (willUnpin) {
      setForcedToolIds([]);
    }
  }, [
    baseDisableAllSources,
    internalSearchTool,
    forcedToolIds,
    setForcedToolIds,
  ]);

  const toggleSource = useCallback(
    (sourceUniqueKey: string) => {
      const wasEnabled = isSourceEnabled(sourceUniqueKey);
      baseToggleSource(sourceUniqueKey);

      if (internalSearchTool) {
        if (!wasEnabled) {
          setForcedToolIds([internalSearchTool.id]);
        } else {
          const allSources = getConfiguredSources(effectiveAvailableSources);
          const remainingEnabled = allSources.filter(
            (s) =>
              s.uniqueKey !== sourceUniqueKey && isSourceEnabled(s.uniqueKey)
          );
          if (
            remainingEnabled.length === 0 &&
            forcedToolIds.includes(internalSearchTool.id)
          ) {
            setForcedToolIds([]);
          }
        }
      }
    },
    [
      baseToggleSource,
      internalSearchTool,
      isSourceEnabled,
      effectiveAvailableSources,
      forcedToolIds,
      setForcedToolIds,
    ]
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

  const searchToolId =
    displayTools.find((tool) => tool.in_code_tool_id === SEARCH_TOOL_ID)?.id ??
    null;

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

  // No separate MCP tool loading; tools already exist in agent.tools

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
    return (
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
    isEnabled: !disabledToolIds.includes(tool.id),
    onToggle: () => toggleToolForCurrentAgent(tool.id),
  }));

  const mcpAllDisabled = selectedMcpTools.every((tool) =>
    disabledToolIds.includes(tool.id)
  );

  const disableAllToolsForSelectedServer = () => {
    if (!selectedMcpServer) return;
    const serverToolIds = selectedMcpTools.map((tool) => tool.id);
    const merged = Array.from(new Set([...disabledToolIds, ...serverToolIds]));
    setSpecificAgentPreferences(agent.id, {
      disabled_tool_ids: merged,
    });
    setForcedToolIds(forcedToolIds.filter((id) => !serverToolIds.includes(id)));
  };

  const enableAllToolsForSelectedServer = () => {
    if (!selectedMcpServer) return;
    const serverToolIdSet = new Set(selectedMcpTools.map((tool) => tool.id));
    setSpecificAgentPreferences(agent.id, {
      disabled_tool_ids: disabledToolIds.filter(
        (id) => !serverToolIdSet.has(id)
      ),
    });
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
    <LineItem
      disabled={selectedMcpServerData?.isLoading}
      onClick={handleFooterReauthClick}
      icon={selectedMcpServerData?.isLoading ? SvgSimpleLoader : SvgKey}
    >
      Re-authenticate
    </LineItem>
  ) : undefined;

  const configuredSources = getConfiguredSources(effectiveAvailableSources);

  const numSourcesEnabled = configuredSources.filter((source) =>
    isSourceEnabled(source.uniqueKey)
  ).length;
  const searchToolDisabled =
    searchToolId !== null && disabledToolIds.includes(searchToolId);

  // Sync search tool state with sources on mount/when states change
  useEffect(() => {
    if (searchToolId === null || !sourcesInitialized) return;

    const hasEnabledSources = numSourcesEnabled > 0;
    if (hasEnabledSources && searchToolDisabled) {
      // Sources are enabled but search tool is disabled - enable it
      toggleToolForCurrentAgent(searchToolId);
    } else if (!hasEnabledSources && !searchToolDisabled) {
      // No sources enabled but search tool is enabled - disable it
      toggleToolForCurrentAgent(searchToolId);
    }
  }, [
    searchToolId,
    numSourcesEnabled,
    searchToolDisabled,
    sourcesInitialized,
    toggleToolForCurrentAgent,
  ]);

  // Set search tool to a specific enabled/disabled state (only toggles if needed)
  const setSearchToolEnabled = (enabled: boolean) => {
    if (searchToolId === null) return;

    if (enabled && searchToolDisabled) {
      toggleToolForCurrentAgent(searchToolId);
    } else if (!enabled && !searchToolDisabled) {
      toggleToolForCurrentAgent(searchToolId);
    }
  };

  const handleSourceToggle = (sourceUniqueKey: string) => {
    const willEnable = !isSourceEnabled(sourceUniqueKey);
    const newEnabledCount = numSourcesEnabled + (willEnable ? 1 : -1);

    toggleSource(sourceUniqueKey);
    setSearchToolEnabled(newEnabledCount > 0);
  };

  const handleDisableAllSources = () => {
    disableAllSources();
    setSearchToolEnabled(false);
  };

  const handleEnableAllSources = () => {
    enableAllSources();
    setSearchToolEnabled(true);
  };

  const handleToggleTool = (toolId: number) => {
    const wasDisabled = disabledToolIds.includes(toolId);
    toggleToolForCurrentAgent(toolId);

    if (toolId === searchToolId) {
      if (wasDisabled) {
        // Enabling - restore previous sources or enable all (persisted to localStorage)
        const previous = previouslyEnabledSourcesRef.current;
        if (previous.length > 0) {
          enableSources(previous);
        } else {
          baseEnableAllSources();
        }
        previouslyEnabledSourcesRef.current = [];
      } else {
        // Disabling - store current sources then disable all (persisted to localStorage)
        previouslyEnabledSourcesRef.current = [...selectedSources];
        baseDisableAllSources();
      }
    }
  };

  const sourceToggleItems: SwitchListItem[] = configuredSources.map(
    (source) => ({
      id: source.uniqueKey,
      label: source.displayName,
      leading: <SourceIcon sourceType={source.internalName} iconSize={16} />,
      isEnabled: isSourceEnabled(source.uniqueKey),
      onToggle: () => handleSourceToggle(source.uniqueKey),
    })
  );

  const allSourcesDisabled = configuredSources.every(
    (source) => !isSourceEnabled(source.uniqueKey)
  );

  const enabledSourceCount = configuredSources.filter((source) =>
    isSourceEnabled(source.uniqueKey)
  ).length;
  const totalSourceCount = configuredSources.length;

  const primaryView = (
    <PopoverMenu>
      {[
        <InputTypeIn
          key="search"
          placeholder="Search actions..."
          searchIcon
          value={searchTerm}
          onChange={(event) => setSearchTerm(event.target.value)}
          ref={focusOnMount}
          variant="internal"
        />,

        // Actions
        ...filteredTools.map((tool) =>
          (() => {
            const isToolAvailable = availableToolIdSet.has(tool.id);
            const isUnavailable =
              !isToolAvailable && tool.in_code_tool_id !== SEARCH_TOOL_ID;
            const canAdminConfigure = hasPermission(
              permissions,
              Permission.MANAGE_ACTIONS
            );
            const adminConfigureInfo =
              isUnavailable && canAdminConfigure
                ? getAdminConfigureInfo(tool)
                : null;
            return (
              <ActionLineItem
                key={tool.id}
                tool={tool}
                disabled={disabledToolIds.includes(tool.id)}
                isForced={forcedToolIds.includes(tool.id)}
                isUnavailable={isUnavailable}
                tooltip={getToolTooltip(
                  tool,
                  isToolAvailable,
                  canAdminConfigure
                )}
                showAdminConfigure={!!adminConfigureInfo}
                adminConfigureHref={adminConfigureInfo?.href}
                adminConfigureTooltip={adminConfigureInfo?.tooltip}
                onToggle={() => handleToggleTool(tool.id)}
                onForceToggle={() =>
                  handleForceToggleWithTracking(
                    tool.id,
                    forcedToolIds.includes(tool.id)
                  )
                }
                onSourceManagementOpen={() =>
                  setSecondaryView({ type: "sources" })
                }
                hasNoConnectors={hasNoConnectors}
                toolAuthStatus={getToolAuthStatus(tool)}
                onOAuthAuthenticate={() => authenticateTool(tool)}
                onClose={() => setOpen(false)}
                sourceCounts={{
                  enabled: enabledSourceCount,
                  total: totalSourceCount,
                }}
              />
            );
          })()
        ),

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
            (t) => !disabledToolIds.includes(t.id)
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
          <LineItem
            href={ADMIN_ROUTES.MCP_ACTIONS.path}
            icon={SvgActions}
            key="more-actions"
          >
            More Actions
          </LineItem>
        ),
      ]}
    </PopoverMenu>
  );

  const toolsView = (
    <SwitchList
      items={sourceToggleItems}
      searchPlaceholder="Search Filters"
      allDisabled={allSourcesDisabled}
      onDisableAll={handleDisableAllSources}
      onEnableAll={handleEnableAllSources}
      disableAllLabel="Disable All Sources"
      enableAllLabel="Enable All Sources"
      onBack={() => setSecondaryView(null)}
    />
  );

  const mcpView = (
    <SwitchList
      items={mcpToggleItems}
      searchPlaceholder={`Search ${selectedMcpServer?.name ?? "server"} tools`}
      allDisabled={mcpAllDisabled}
      onDisableAll={disableAllToolsForSelectedServer}
      onEnableAll={enableAllToolsForSelectedServer}
      disableAllLabel="Disable All Tools"
      enableAllLabel="Enable All Tools"
      onBack={() => setSecondaryView(null)}
      footer={mcpFooter}
    />
  );

  // If no tools or MCP servers are available, don't render the component
  if (displayTools.length === 0 && mcpServers.length === 0) return null;

  return (
    <>
      <Popover open={open} onOpenChange={handleOpenChange}>
        <Popover.Trigger asChild>
          <div data-testid="action-management-toggle">
            <Button
              disabled={disabled}
              icon={SvgSliders}
              interaction={open ? "hover" : "rest"}
              prominence="tertiary"
              tooltip="Manage Actions"
            />
          </div>
        </Popover.Trigger>
        <Popover.Content side="bottom" align="start" width="lg">
          <div data-testid="tool-options">
            {secondaryView
              ? secondaryView.type === "mcp"
                ? mcpView
                : toolsView
              : primaryView}
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
    </>
  );
}
