"use client";

import {
  FILE_READER_TOOL_ID,
  IMAGE_GENERATION_TOOL_ID,
  PYTHON_TOOL_ID,
  SEARCH_TOOL_ID,
  WEB_SEARCH_TOOL_ID,
} from "@/app/app/components/tools/constants";
import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import SwitchList, {
  SwitchListItem,
} from "@/refresh-components/popovers/ActionsPopover/SwitchList";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import {
  MCPAuthenticationType,
  MCPAuthenticationPerformer,
  ToolSnapshot,
} from "@/lib/tools/interfaces";
import { useForcedTools } from "@/lib/hooks/useForcedTools";
import useAgentPreferences from "@/hooks/useAgentPreferences";
import { useUser } from "@/providers/UserProvider";
import { FilterManager, useSourcePreferences } from "@/lib/hooks";
import { listSourceMetadata } from "@/lib/sources";
import MCPApiKeyModal from "@/components/chat/MCPApiKeyModal";
import { ValidSources } from "@/lib/types";
import { SourceMetadata } from "@/lib/search/interfaces";
import { SourceIcon } from "@/components/SourceIcon";
import { useAvailableTools } from "@/hooks/useAvailableTools";
import useCCPairs from "@/hooks/useCCPairs";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { useToolOAuthStatus } from "@/lib/hooks/useToolOAuthStatus";
import LineItem from "@/refresh-components/buttons/LineItem";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import ActionLineItem from "@/refresh-components/popovers/ActionsPopover/ActionLineItem";
import MCPLineItem, {
  MCPServer,
} from "@/refresh-components/popovers/ActionsPopover/MCPLineItem";
import { useProjectsContext } from "@/providers/ProjectsContext";
import { SvgActions, SvgChevronRight, SvgKey, SvgSliders } from "@opal/icons";
import { Button } from "@opal/components";

const UNAVAILABLE_TOOL_TOOLTIP_FALLBACK =
  "This action is not configured yet. Ask an admin to enable it.";
const UNAVAILABLE_TOOL_TOOLTIP_ADMIN_FALLBACK =
  "This action is not configured yet. If you have access, enable it in the admin panel.";
const UNAVAILABLE_TOOL_TOOLTIPS: Record<string, string> = {
  [IMAGE_GENERATION_TOOL_ID]:
    "Image generation requires a configured model. If you have access, set one up under Settings > Image Generation, or ask an admin.",
  [WEB_SEARCH_TOOL_ID]:
    "Web search requires a configured provider. If you have access, set one up under Settings > Web Search, or ask an admin.",
  [PYTHON_TOOL_ID]:
    "Code Interpreter requires the service to be configured with a valid base URL. If you have access, configure it in the admin panel, or ask an admin.",
};
const getUnavailableToolTooltip = (
  inCodeToolId?: string | null,
  canAdminConfigure?: boolean
) =>
  (inCodeToolId && UNAVAILABLE_TOOL_TOOLTIPS[inCodeToolId]) ??
  (canAdminConfigure
    ? UNAVAILABLE_TOOL_TOOLTIP_ADMIN_FALLBACK
    : UNAVAILABLE_TOOL_TOOLTIP_FALLBACK);

const ADMIN_CONFIG_LINKS: Record<string, { href: string; tooltip: string }> = {
  [IMAGE_GENERATION_TOOL_ID]: {
    href: "/admin/configuration/image-generation",
    tooltip: "Configure Image Generation",
  },
  [WEB_SEARCH_TOOL_ID]: {
    href: "/admin/configuration/web-search",
    tooltip: "Configure Web Search",
  },
  KnowledgeGraphTool: {
    href: "/admin/kg",
    tooltip: "Configure Knowledge Graph",
  },
};

const OPENAPI_ADMIN_CONFIG = {
  href: "/admin/actions/open-api",
  tooltip: "Manage OpenAPI Actions",
};

const getAdminConfigureInfo = (
  tool: ToolSnapshot
): { href: string; tooltip: string } | null => {
  if (tool.in_code_tool_id && ADMIN_CONFIG_LINKS[tool.in_code_tool_id]) {
    return ADMIN_CONFIG_LINKS[tool.in_code_tool_id] ?? null;
  }

  if (!tool.in_code_tool_id && !tool.mcp_server_id) {
    return OPENAPI_ADMIN_CONFIG;
  }

  return null;
};

// Get source metadata for configured sources - deduplicated by source type
function getConfiguredSources(
  availableSources: ValidSources[]
): Array<SourceMetadata & { originalName: string; uniqueKey: string }> {
  const allSources = listSourceMetadata();

  const seenSources = new Set<string>();
  const configuredSources: Array<
    SourceMetadata & { originalName: string; uniqueKey: string }
  > = [];

  availableSources.forEach((sourceName) => {
    // Handle federated connectors by removing the federated_ prefix
    const cleanName = sourceName.replace("federated_", "");
    // Skip if we've already seen this source type
    if (seenSources.has(cleanName)) return;
    seenSources.add(cleanName);
    const source = allSources.find(
      (source) => source.internalName === cleanName
    );
    if (source) {
      configuredSources.push({
        ...source,
        originalName: sourceName,
        uniqueKey: cleanName,
      });
    }
  });
  return configuredSources;
}

type SecondaryViewState =
  | { type: "sources" }
  | { type: "mcp"; serverId: number };

export interface ActionsPopoverProps {
  selectedAssistant: MinimalPersonaSnapshot;
  filterManager: FilterManager;
  availableSources?: ValidSources[];
  disabled?: boolean;
}

export default function ActionsPopover({
  selectedAssistant,
  filterManager,
  availableSources = [],
  disabled = false,
}: ActionsPopoverProps) {
  const [open, setOpen] = useState(false);
  const [secondaryView, setSecondaryView] = useState<SecondaryViewState | null>(
    null
  );
  const [searchTerm, setSearchTerm] = useState("");
  // const [showFadeMask, setShowFadeMask] = useState(false);
  // const [showTopShadow, setShowTopShadow] = useState(false);
  const { selectedSources, setSelectedSources } = filterManager;
  const [mcpServers, setMcpServers] = useState<MCPServer[]>([]);

  // Use the OAuth hook
  const { getToolAuthStatus, authenticateTool } = useToolOAuthStatus(
    selectedAssistant.id
  );

  const {
    sourcesInitialized,
    enableSources,
    enableAllSources: baseEnableAllSources,
    disableAllSources: baseDisableAllSources,
    toggleSource: baseToggleSource,
    isSourceEnabled,
  } = useSourcePreferences({
    availableSources,
    selectedSources,
    setSelectedSources,
  });

  // Store previously enabled sources when search tool is disabled
  const previouslyEnabledSourcesRef = useRef<SourceMetadata[]>([]);

  const isDefaultAgent = selectedAssistant.id === 0;

  // Get sources the agent has access to via document sets, hierarchy nodes, and attached documents
  // Default agent has access to all sources
  const agentAccessibleSources = useMemo(() => {
    if (isDefaultAgent) {
      return null; // null means "all accessible"
    }

    const sourceSet = new Set<string>();

    // Add sources from document sets
    selectedAssistant.document_sets.forEach((docSet) => {
      // Check cc_pair_summaries (regular connectors)
      docSet.cc_pair_summaries?.forEach((ccPair) => {
        // Normalize by removing federated_ prefix
        const normalized = ccPair.source.replace("federated_", "");
        sourceSet.add(normalized);
      });

      // Check federated_connector_summaries (federated connectors)
      docSet.federated_connector_summaries?.forEach((fedConnector) => {
        // Normalize by removing federated_ prefix
        const normalized = fedConnector.source.replace("federated_", "");
        sourceSet.add(normalized);
      });
    });

    // Add sources from hierarchy nodes and attached documents (via knowledge_sources)
    selectedAssistant.knowledge_sources?.forEach((source) => {
      // Normalize by removing federated_ prefix
      const normalized = source.replace("federated_", "");
      sourceSet.add(normalized);
    });

    // No specific sources selected means everything is searchable
    if (sourceSet.size === 0) return null;

    return sourceSet;
  }, [
    isDefaultAgent,
    selectedAssistant.document_sets,
    selectedAssistant.knowledge_sources,
  ]);

  // Store MCP server auth/loading state (tools are part of selectedAssistant.tools)
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

  // Get the assistant preference for this assistant
  const { assistantPreferences, setSpecificAssistantPreferences } =
    useAgentPreferences();
  const { forcedToolIds, setForcedToolIds } = useForcedTools();

  // Reset state when assistant changes
  useEffect(() => {
    setForcedToolIds([]);
  }, [selectedAssistant.id, setForcedToolIds]);

  const { isAdmin, isCurator } = useUser();

  const { tools: availableTools } = useAvailableTools();
  const { ccPairs } = useCCPairs();
  const { currentProjectId, allCurrentProjectFiles } = useProjectsContext();
  const availableToolIdSet = new Set(availableTools.map((tool) => tool.id));

  // Check if there are any connectors available
  const hasNoConnectors = ccPairs.length === 0;

  const assistantPreference = assistantPreferences?.[selectedAssistant.id];
  const disabledToolIds = assistantPreference?.disabled_tool_ids || [];
  const toggleToolForCurrentAssistant = (toolId: number) => {
    const disabled = disabledToolIds.includes(toolId);
    setSpecificAssistantPreferences(selectedAssistant.id, {
      disabled_tool_ids: disabled
        ? disabledToolIds.filter((id) => id !== toolId)
        : [...disabledToolIds, toolId],
    });

    // If we're disabling a tool that is currently forced, remove it from forced tools
    if (!disabled && forcedToolIds.includes(toolId)) {
      setForcedToolIds(forcedToolIds.filter((id) => id !== toolId));
    }
  };

  const toggleForcedTool = (toolId: number) => {
    if (forcedToolIds.includes(toolId)) {
      // If clicking on already forced tool, unforce it
      setForcedToolIds([]);
    } else {
      // If clicking on a new tool, replace any existing forced tools with just this one
      setForcedToolIds([toolId]);
    }
  };

  // Get internal search tool reference for auto-pin logic
  const internalSearchTool = useMemo(
    () =>
      selectedAssistant.tools.find(
        (tool) => tool.in_code_tool_id === SEARCH_TOOL_ID && !tool.mcp_server_id
      ),
    [selectedAssistant.tools]
  );

  // Handle explicit force toggle from ActionLineItem
  const handleForceToggleWithTracking = useCallback(
    (toolId: number, wasForced: boolean) => {
      // If pinning internal search, enable all accessible sources
      if (
        !wasForced &&
        internalSearchTool &&
        toolId === internalSearchTool.id
      ) {
        const sources = getConfiguredSources(availableSources);
        const accessibleSources = sources.filter(
          (s) =>
            agentAccessibleSources === null ||
            agentAccessibleSources.has(s.uniqueKey)
        );
        setSelectedSources(accessibleSources);
      }
      toggleForcedTool(toolId);
    },
    [
      toggleForcedTool,
      internalSearchTool,
      availableSources,
      agentAccessibleSources,
      setSelectedSources,
    ]
  );

  // Wrapped source functions that auto-pin internal search when sources change
  const enableAllSources = useCallback(() => {
    // Only enable sources the agent has access to
    const allConfiguredSources = getConfiguredSources(availableSources);
    const accessibleSources = allConfiguredSources.filter(
      (s) =>
        agentAccessibleSources === null ||
        agentAccessibleSources.has(s.uniqueKey)
    );
    setSelectedSources(accessibleSources);

    if (internalSearchTool) {
      setForcedToolIds([internalSearchTool.id]);
    }
  }, [
    agentAccessibleSources,
    availableSources,
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

      const configuredSources = getConfiguredSources(availableSources);

      if (internalSearchTool) {
        if (!wasEnabled) {
          // Enabling a source - auto-pin internal search
          setForcedToolIds([internalSearchTool.id]);
        } else {
          // Disabling a source - check if all sources will be disabled
          const remainingEnabled = configuredSources.filter(
            (s) =>
              s.uniqueKey !== sourceUniqueKey && isSourceEnabled(s.uniqueKey)
          );
          if (
            remainingEnabled.length === 0 &&
            forcedToolIds.includes(internalSearchTool.id)
          ) {
            // All sources disabled - unpin
            setForcedToolIds([]);
          }
        }
      }
    },
    [
      baseToggleSource,
      internalSearchTool,
      isSourceEnabled,
      availableSources,
      forcedToolIds,
      setForcedToolIds,
    ]
  );

  // Filter out MCP tools from the main list (they have mcp_server_id)
  // Also filter out internal search tool for basic users when there are no connectors
  // Also filter out tools that are not chat-selectable (e.g., OpenURL)
  const displayTools = selectedAssistant.tools.filter((tool) => {
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
    if (tool.in_code_tool_id === SEARCH_TOOL_ID && (isAdmin || isCurator)) {
      return true;
    }

    // Filter out internal search tool for non-admin/curator users when there are no connectors
    if (
      tool.in_code_tool_id === SEARCH_TOOL_ID &&
      hasNoConnectors &&
      !isAdmin &&
      !isCurator
    ) {
      return false;
    }

    return true;
  });

  const searchToolId =
    displayTools.find((tool) => tool.in_code_tool_id === SEARCH_TOOL_ID)?.id ??
    null;

  // Fetch MCP servers for the assistant on mount
  useEffect(() => {
    if (selectedAssistant == null || selectedAssistant.id == null) return;

    const abortController = new AbortController();

    const fetchMCPServers = async () => {
      try {
        const response = await fetch(
          `/api/mcp/servers/persona/${selectedAssistant.id}`,
          {
            signal: abortController.signal,
          }
        );
        if (response.ok) {
          const data = await response.json();
          const servers = data.mcp_servers || [];
          setMcpServers(servers);
          // Seed auth/loading state based on response
          setMcpServerData((prev) => {
            const next = { ...prev } as any;
            servers.forEach((s: any) => {
              next[s.id as number] = {
                isAuthenticated: !!s.user_authenticated || !!s.is_authenticated,
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
  }, [selectedAssistant?.id]);

  // No separate MCP tool loading; tools already exist in selectedAssistant.tools

  // Handle MCP authentication
  const handleMCPAuthenticate = async (
    serverId: number,
    authType: MCPAuthenticationType
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
        const response = await fetch("/api/mcp/oauth/connect", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            server_id: serverId,
            return_path: window.location.pathname + window.location.search,
            include_resource_param: true,
          }),
        });

        if (response.ok) {
          const { oauth_url } = await response.json();
          window.location.href = oauth_url;
        } else {
          updateLoadingState(false);
        }
      } catch (error) {
        console.error("Error initiating OAuth:", error);
        updateLoadingState(false);
      }
    }
  };

  const handleMCPApiKeySubmit = async (serverId: number, apiKey: string) => {
    try {
      const response = await fetch("/api/mcp/user-credentials", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          server_id: serverId,
          credentials: { api_key: apiKey },
          transport: "streamable-http",
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        const errorMessage = errorData.detail || "Failed to save API key";
        throw new Error(errorMessage);
      }
    } catch (error) {
      console.error("Error saving API key:", error);
      throw error;
    }
  };

  const handleMCPCredentialsSubmit = async (
    serverId: number,
    credentials: Record<string, string>
  ) => {
    try {
      const response = await fetch("/api/mcp/user-credentials", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          server_id: serverId,
          credentials: credentials,
          transport: "streamable-http",
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        const errorMessage = errorData.detail || "Failed to save credentials";
        throw new Error(errorMessage);
      }
    } catch (error) {
      console.error("Error saving credentials:", error);
      throw error;
    }
  };

  const handleServerAuthentication = (server: MCPServer) => {
    const authType = server.auth_type;
    const performer = server.auth_performer;

    if (
      authType === MCPAuthenticationType.NONE ||
      performer === MCPAuthenticationPerformer.ADMIN
    ) {
      return;
    }

    if (authType === MCPAuthenticationType.OAUTH) {
      handleMCPAuthenticate(server.id, MCPAuthenticationType.OAUTH);
    } else if (authType === MCPAuthenticationType.API_TOKEN) {
      setMcpApiKeyModal({
        isOpen: true,
        serverId: server.id,
        serverName: server.name,
        authTemplate: server.auth_template,
        onSuccess: () => {
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
        isAuthenticated: server.user_authenticated,
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
      ? selectedAssistant.tools.filter(
          (t) => t.mcp_server_id === Number(selectedMcpServerId)
        )
      : [];
  const selectedMcpServerData = selectedMcpServer
    ? mcpServerData[selectedMcpServer.id]
    : undefined;
  const isActiveServerAuthenticated =
    selectedMcpServerData?.isAuthenticated ??
    !!(
      selectedMcpServer?.user_authenticated ||
      selectedMcpServer?.is_authenticated
    );
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
    onToggle: () => toggleToolForCurrentAssistant(tool.id),
  }));

  const mcpAllDisabled = selectedMcpTools.every((tool) =>
    disabledToolIds.includes(tool.id)
  );

  const disableAllToolsForSelectedServer = () => {
    if (!selectedMcpServer) return;
    const serverToolIds = selectedMcpTools.map((tool) => tool.id);
    const merged = Array.from(new Set([...disabledToolIds, ...serverToolIds]));
    setSpecificAssistantPreferences(selectedAssistant.id, {
      disabled_tool_ids: merged,
    });
    setForcedToolIds(forcedToolIds.filter((id) => !serverToolIds.includes(id)));
  };

  const enableAllToolsForSelectedServer = () => {
    if (!selectedMcpServer) return;
    const serverToolIdSet = new Set(selectedMcpTools.map((tool) => tool.id));
    setSpecificAssistantPreferences(selectedAssistant.id, {
      disabled_tool_ids: disabledToolIds.filter(
        (id) => !serverToolIdSet.has(id)
      ),
    });
  };

  const handleFooterReauthClick = () => {
    if (selectedMcpServer) {
      handleServerAuthentication(selectedMcpServer);
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
      onClick={handleFooterReauthClick}
      icon={selectedMcpServerData?.isLoading ? SimpleLoader : SvgKey}
      rightChildren={
        <Button icon={SvgChevronRight} prominence="tertiary" size="sm" />
      }
    >
      Re-Authenticate
    </LineItem>
  ) : undefined;

  const configuredSources = getConfiguredSources(availableSources);

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
      toggleToolForCurrentAssistant(searchToolId);
    } else if (!hasEnabledSources && !searchToolDisabled) {
      // No sources enabled but search tool is enabled - disable it
      toggleToolForCurrentAssistant(searchToolId);
    }
  }, [
    searchToolId,
    numSourcesEnabled,
    searchToolDisabled,
    sourcesInitialized,
    toggleToolForCurrentAssistant,
  ]);

  // Set search tool to a specific enabled/disabled state (only toggles if needed)
  const setSearchToolEnabled = (enabled: boolean) => {
    if (searchToolId === null) return;

    if (enabled && searchToolDisabled) {
      toggleToolForCurrentAssistant(searchToolId);
    } else if (!enabled && !searchToolDisabled) {
      toggleToolForCurrentAssistant(searchToolId);
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
    toggleToolForCurrentAssistant(toolId);

    if (toolId === searchToolId) {
      if (wasDisabled) {
        // Enabling - restore previous sources or enable all (no persistence)
        const previous = previouslyEnabledSourcesRef.current;
        if (previous.length > 0) {
          setSelectedSources(previous);
        } else {
          setSelectedSources(configuredSources);
        }
        previouslyEnabledSourcesRef.current = [];
      } else {
        // Disabling - store current sources then disable all (no persistence)
        previouslyEnabledSourcesRef.current = [...selectedSources];
        setSelectedSources([]);
      }
    }
  };

  // Only show sources the agent has access to
  const accessibleConfiguredSources = configuredSources.filter(
    (source) =>
      agentAccessibleSources === null ||
      agentAccessibleSources.has(source.uniqueKey)
  );

  const sourceToggleItems: SwitchListItem[] = accessibleConfiguredSources.map(
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

  // Count enabled sources for display (only accessible sources)
  const enabledSourceCount = accessibleConfiguredSources.filter((source) =>
    isSourceEnabled(source.uniqueKey)
  ).length;
  const totalSourceCount = accessibleConfiguredSources.length;

  const primaryView = (
    <PopoverMenu>
      {[
        <InputTypeIn
          key="search"
          placeholder="Search Actions"
          value={searchTerm}
          onChange={(event) => setSearchTerm(event.target.value)}
          autoFocus
          variant="internal"
        />,

        // Actions
        ...filteredTools.map((tool) =>
          (() => {
            const isToolAvailable = availableToolIdSet.has(tool.id);
            const isUnavailable =
              !isToolAvailable && tool.in_code_tool_id !== SEARCH_TOOL_ID;
            const canAdminConfigure = isAdmin || isCurator;
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
                unavailableReason={
                  isUnavailable
                    ? getUnavailableToolTooltip(
                        tool.in_code_tool_id,
                        canAdminConfigure
                      )
                    : undefined
                }
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
            isAuthenticated:
              !!server.user_authenticated || !!server.is_authenticated,
            isLoading: false,
          };

          // Tools for this server come from assistant.tools
          const serverTools = selectedAssistant.tools.filter(
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

        (isAdmin || isCurator) && (
          <LineItem href="/admin/actions" icon={SvgActions} key="more-actions">
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
              icon={SvgSliders}
              transient={open}
              prominence="tertiary"
              tooltip="Manage Actions"
              disabled={disabled}
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
