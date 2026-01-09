"use client";

import { SEARCH_TOOL_ID } from "@/app/chat/components/tools/constants";
import { useState, useEffect } from "react";
import {
  Popover,
  PopoverContent,
  PopoverMenu,
  PopoverTrigger,
} from "@/components/ui/popover";
import SwitchList, {
  SwitchListItem,
} from "@/refresh-components/popovers/ActionsPopover/SwitchList";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import {
  MCPAuthenticationType,
  MCPAuthenticationPerformer,
} from "@/lib/tools/interfaces";
import { useForcedTools } from "@/lib/hooks/useForcedTools";
import { useAssistantPreferences } from "@/app/chat/hooks/useAssistantPreferences";
import { useUser } from "@/components/user/UserProvider";
import { FilterManager, useSourcePreferences } from "@/lib/hooks";
import { listSourceMetadata } from "@/lib/sources";
import MCPApiKeyModal from "@/components/chat/MCPApiKeyModal";
import { ValidSources } from "@/lib/types";
import { SourceMetadata } from "@/lib/search/interfaces";
import { SourceIcon } from "@/components/SourceIcon";
import { useAvailableTools } from "@/hooks/useAvailableTools";
import useCCPairs from "@/hooks/useCCPairs";
import IconButton from "@/refresh-components/buttons/IconButton";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { useToolOAuthStatus } from "@/lib/hooks/useToolOAuthStatus";
import LineItem from "@/refresh-components/buttons/LineItem";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import ActionLineItem from "@/refresh-components/popovers/ActionsPopover/ActionLineItem";
import MCPLineItem, {
  MCPServer,
} from "@/refresh-components/popovers/ActionsPopover/MCPLineItem";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { SvgActions, SvgChevronRight, SvgKey, SvgSliders } from "@opal/icons";

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

  const { enableAllSources, disableAllSources, toggleSource, isSourceEnabled } =
    useSourcePreferences({
      availableSources,
      selectedSources,
      setSelectedSources,
    });

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
    useAssistantPreferences();
  const { forcedToolIds, setForcedToolIds } = useForcedTools();

  const { isAdmin, isCurator } = useUser();

  const { tools: availableTools } = useAvailableTools();
  const { ccPairs } = useCCPairs();
  const { currentProjectId, allCurrentProjectFiles } = useProjectsContext();
  const availableToolIds = availableTools.map((tool) => tool.id);

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

  // Filter out MCP tools from the main list (they have mcp_server_id)
  // and filter out tools that are not available
  // Also filter out internal search tool for basic users when there are no connectors
  // Also filter out tools that are not chat-selectable (e.g., OpenURL)
  const displayTools = selectedAssistant.tools.filter((tool) => {
    // Filter out MCP tools
    if (tool.mcp_server_id) return false;

    // Filter out tools that are not chat-selectable (visibility set by backend)
    if (!tool.chat_selectable) return false;

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

    // Filter out tools that are not available
    if (!availableToolIds.includes(tool.id)) return false;

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
        onSuccess: undefined,
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
      rightChildren={<IconButton icon={SvgChevronRight} internal />}
    >
      Re-Authenticate
    </LineItem>
  ) : undefined;

  const configuredSources = getConfiguredSources(availableSources);

  const sourceToggleItems: SwitchListItem[] = configuredSources.map(
    (source) => ({
      id: source.uniqueKey,
      label: source.displayName,
      leading: <SourceIcon sourceType={source.internalName} iconSize={16} />,
      isEnabled: isSourceEnabled(source.uniqueKey),
      onToggle: () => toggleSource(source.uniqueKey),
    })
  );

  const allSourcesDisabled = configuredSources.every(
    (source) => !isSourceEnabled(source.uniqueKey)
  );

  const primaryView = (
    <PopoverMenu medium>
      {[
        <InputTypeIn
          key="search"
          placeholder="Search Actions"
          value={searchTerm}
          onChange={(event) => setSearchTerm(event.target.value)}
          autoFocus
          internal
        />,

        // Actions
        ...filteredTools.map((tool) => (
          <ActionLineItem
            key={tool.id}
            tool={tool}
            disabled={disabledToolIds.includes(tool.id)}
            isForced={forcedToolIds.includes(tool.id)}
            onToggle={() => toggleToolForCurrentAssistant(tool.id)}
            onForceToggle={() => toggleForcedTool(tool.id)}
            onSourceManagementOpen={() => setSecondaryView({ type: "sources" })}
            hasNoConnectors={hasNoConnectors}
            toolAuthStatus={getToolAuthStatus(tool)}
            onOAuthAuthenticate={() => authenticateTool(tool)}
            onClose={() => setOpen(false)}
          />
        )),

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
      onDisableAll={disableAllSources}
      onEnableAll={enableAllSources}
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
        <PopoverTrigger asChild>
          <div data-testid="action-management-toggle">
            <IconButton
              icon={SvgSliders}
              transient={open}
              tertiary
              tooltip="Manage Actions"
              disabled={disabled}
            />
          </div>
        </PopoverTrigger>
        <PopoverContent side="bottom" align="start">
          <div data-testid="tool-options">
            {secondaryView
              ? secondaryView.type === "mcp"
                ? mcpView
                : toolsView
              : primaryView}
          </div>
        </PopoverContent>
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
