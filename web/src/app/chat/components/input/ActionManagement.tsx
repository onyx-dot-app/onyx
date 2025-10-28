"use client";

import {
  DisableIcon,
  IconProps,
  MoreActionsIcon,
} from "@/components/icons/icons";
import { SEARCH_TOOL_ID } from "@/app/chat/components/tools/constants";
import React, { useState, useEffect, useCallback } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ToggleList, ToggleListItem } from "@/components/ui/togglelist";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import {
  ToolSnapshot,
  MCPAuthenticationType,
  MCPAuthenticationPerformer,
} from "@/lib/tools/interfaces";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";
import { getIconForAction } from "../../services/actionUtils";
import { useUser } from "@/components/user/UserProvider";
import { FilterManager, useSourcePreferences } from "@/lib/hooks";
import { listSourceMetadata } from "@/lib/sources";
import SvgChevronRight from "@/icons/chevron-right";
import SvgKey from "@/icons/key";
import SvgLock from "@/icons/lock";
import SvgCheck from "@/icons/check";
import SvgServer from "@/icons/server";
import { FiKey, FiLoader } from "react-icons/fi";
import { MCPApiKeyModal } from "@/components/chat/MCPApiKeyModal";
import { ValidSources } from "@/lib/types";
import { SourceMetadata } from "@/lib/search/interfaces";
import { SourceIcon } from "@/components/SourceIcon";
import { useChatContext } from "@/refresh-components/contexts/ChatContext";
import IconButton from "@/refresh-components/buttons/IconButton";
import Button from "@/refresh-components/buttons/Button";
import SvgSliders from "@/icons/sliders";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { cn } from "@/lib/utils";
import SvgSettings from "@/icons/settings";
import {
  ToolAuthStatus,
  useToolOAuthStatus,
} from "@/lib/hooks/useToolOAuthStatus";

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

interface ActionItemProps {
  tool?: ToolSnapshot;
  Icon?: (iconProps: IconProps) => JSX.Element;
  label?: string;
  disabled: boolean;
  isForced: boolean;
  onToggle: () => void;
  onForceToggle: () => void;
  onSourceManagementOpen?: () => void;
  hasNoConnectors?: boolean;
  tooltipSide?: "top" | "right" | "bottom" | "left";
  toolAuthStatus?: ToolAuthStatus;
  onOAuthAuthenticate?: () => void;
}

function ActionItem({
  tool,
  Icon: ProvidedIcon,
  label: providedLabel,
  disabled,
  isForced,
  onToggle,
  onForceToggle,
  onSourceManagementOpen,
  hasNoConnectors = false,
  tooltipSide = "left",
  toolAuthStatus,
  onOAuthAuthenticate,
}: ActionItemProps) {
  // If a tool is provided, derive the icon and label from it
  const Icon = tool ? getIconForAction(tool) : ProvidedIcon!;
  const label = tool ? tool.display_name || tool.name : providedLabel!;
  // Generate test ID based on tool name if available
  const toolName = tool?.name || providedLabel || "";

  // Check if this is the internal search tool with no connectors
  const isSearchToolWithNoConnectors =
    tool?.in_code_tool_id === SEARCH_TOOL_ID && hasNoConnectors;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            data-testid={`tool-option-${toolName}`}
            className={cn(
              "group flex items-center justify-between px-2 cursor-pointer hover:bg-background-neutral-01 rounded-lg py-2 mx-1",
              isForced ? "bg-accent-100 hover:bg-accent-200" : ""
            )}
            onClick={() => {
              // If no connectors, don't allow forcing the tool
              if (isSearchToolWithNoConnectors) {
                return;
              }

              // If disabled, un-disable the tool
              if (onToggle && disabled) {
                onToggle();
              }

              onForceToggle();
            }}
          >
            <div
              className={cn(
                "flex items-center gap-2 flex-1",
                isSearchToolWithNoConnectors || disabled ? "opacity-50" : "",
                isForced ? "text-action-link-05" : ""
              )}
            >
              <Icon
                className={cn(
                  "h-[1rem] w-[1rem] stroke-text-04",
                  isForced ? "text-action-link-05" : "text-text-03"
                )}
              />
              <Text
                className={cn(
                  "text-sm font-medium select-none",
                  isSearchToolWithNoConnectors || disabled ? "line-through" : ""
                )}
              >
                {label}
              </Text>
            </div>
            <div className="flex items-center gap-2">
              {/* OAuth Authentication Indicator */}
              {tool?.oauth_config_id && toolAuthStatus && (
                <div
                  className="flex items-center gap-2 transition-opacity duration-200 opacity-0 group-hover:opacity-100"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (
                      !toolAuthStatus.hasToken ||
                      toolAuthStatus.isTokenExpired
                    ) {
                      onOAuthAuthenticate?.();
                    }
                  }}
                >
                  {!toolAuthStatus.hasToken || toolAuthStatus.isTokenExpired ? (
                    <SvgKey
                      className={cn(
                        "h-[1rem] w-[1rem]",
                        "transition-colors",
                        "cursor-pointer",
                        "stroke-yellow-500",
                        "hover:stroke-yellow-600"
                      )}
                    />
                  ) : (
                    <SvgCheck className="stroke-status-text-success-05 h-[1rem] w-[1rem]" />
                  )}
                </div>
              )}
              {!isSearchToolWithNoConnectors && (
                <div
                  className={cn(
                    "flex items-center gap-2 transition-opacity duration-200",
                    disabled
                      ? "opacity-100"
                      : "opacity-0 group-hover:opacity-100"
                  )}
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggle();
                  }}
                >
                  <DisableIcon
                    className={cn(
                      "transition-colors cursor-pointer",
                      disabled
                        ? "text-text-05 hover:text-text-03"
                        : "text-text-03 hover:text-text-05"
                    )}
                  />
                </div>
              )}
              {tool && tool.in_code_tool_id === SEARCH_TOOL_ID && (
                <div
                  className={cn(
                    "flex items-center gap-2 transition-opacity duration-200",
                    isSearchToolWithNoConnectors
                      ? "opacity-0 group-hover:opacity-100"
                      : ""
                  )}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (isSearchToolWithNoConnectors) {
                      // Navigate to add connector page
                      window.location.href = "/admin/add-connector";
                    } else {
                      onSourceManagementOpen?.();
                    }
                  }}
                >
                  {isSearchToolWithNoConnectors ? (
                    <SvgSettings
                      width={16}
                      height={16}
                      className="transition-colors cursor-pointer stroke-text-02 hover:text-text-05"
                    />
                  ) : (
                    <SvgChevronRight
                      width={16}
                      height={16}
                      className="transition-colors cursor-pointer stroke-text-02 hover:text-text-05"
                    />
                  )}
                </div>
              )}
            </div>
          </div>
        </TooltipTrigger>
        {tool?.description && (
          <TooltipContent side={tooltipSide} width="max-w-xs">
            <Text inverted>{tool.description}</Text>
          </TooltipContent>
        )}
      </Tooltip>
    </TooltipProvider>
  );
}

interface MCPServer {
  id: number;
  name: string;
  server_url: string;
  auth_type: MCPAuthenticationType;
  auth_performer: MCPAuthenticationPerformer;
  is_authenticated: boolean;
  user_authenticated?: boolean;
  auth_template?: any;
  user_credentials?: Record<string, string>;
}

type SecondaryViewState =
  | { type: "sources" }
  | { type: "mcp"; serverId: number };

interface MCPServerItemProps {
  server: MCPServer;
  isActive: boolean;
  onSelect: () => void;
  onAuthenticate: () => void;
  tools: ToolSnapshot[];
  enabledTools: ToolSnapshot[];
  isAuthenticated: boolean;
  isLoading: boolean;
}

function MCPServerItem({
  server,
  isActive,
  onSelect,
  onAuthenticate,
  tools,
  enabledTools,
  isAuthenticated,
  isLoading,
}: MCPServerItemProps) {
  const showAuthTrigger =
    server.auth_performer === MCPAuthenticationPerformer.PER_USER &&
    server.auth_type !== MCPAuthenticationType.NONE;
  const showInlineReauth =
    showAuthTrigger && isAuthenticated && tools.length > 0;
  const showReauthButton =
    showAuthTrigger && isAuthenticated && !showInlineReauth;

  const getServerIcon = () => {
    if (isLoading) {
      return <FiLoader className="animate-spin" />;
    }
    if (isAuthenticated) {
      return <SvgCheck width={14} height={14} className="stroke-green-500" />;
    }
    if (server.auth_type === MCPAuthenticationType.NONE) {
      return <SvgServer width={14} height={14} className="stroke-text-02" />;
    }
    if (server.auth_performer === MCPAuthenticationPerformer.PER_USER) {
      return <FiKey width={14} height={14} className="stroke-yellow-500" />;
    }
    return <SvgLock width={14} height={14} className="stroke-red-500" />;
  };

  const handleClick = (event: React.MouseEvent) => {
    event.stopPropagation();
    if (isAuthenticated && tools.length > 0) {
      onSelect();
      return;
    }
    if (showAuthTrigger) {
      onAuthenticate();
    }
  };

  const allToolsDisabled = enabledTools.length === 0 && tools.length > 0;

  return (
    <div
      className={cn(
        "group flex items-center justify-between px-2 cursor-pointer hover:bg-background-neutral-01 rounded-lg py-2 mx-1",
        isActive ? "bg-accent-100 hover:bg-accent-200" : "",
        allToolsDisabled ? "opacity-60" : ""
      )}
      onClick={handleClick}
      data-mcp-server-id={server.id}
      data-mcp-server-name={server.name}
    >
      <div className="flex items-center gap-2 flex-1 min-w-0">
        {getServerIcon()}
        <Text
          className={cn(
            "text-sm font-medium select-none truncate max-w-[120px] inline-block align-middle",
            allToolsDisabled ? "line-through" : ""
          )}
          title={server.name}
        >
          {server.name}
        </Text>
        {isAuthenticated &&
          tools.length > 0 &&
          enabledTools.length > 0 &&
          tools.length !== enabledTools.length && (
            <Text className="text-xs whitespace-nowrap ml-1 flex-shrink-0 text-text-04">
              <Text className="inline text-action-link-05">
                {enabledTools.length}
              </Text>
              {` of ${tools.length}`}
            </Text>
          )}
      </div>
      <div className="flex items-center gap-1">
        {showReauthButton && (
          <IconButton
            icon={SvgKey}
            tertiary
            aria-label="Re-authenticate MCP server"
            title="Re-authenticate"
            onClick={(event) => {
              event.stopPropagation();
              onAuthenticate();
            }}
          />
        )}
        {isAuthenticated && tools.length > 0 && (
          <SvgChevronRight
            width={14}
            height={14}
            className="transition-transform stroke-text-02"
          />
        )}
      </div>
    </div>
  );
}

interface ActionToggleProps {
  selectedAssistant: MinimalPersonaSnapshot;
  filterManager: FilterManager;
  availableSources?: ValidSources[];
}

export function ActionToggle({
  selectedAssistant,
  filterManager,
  availableSources = [],
}: ActionToggleProps) {
  const [open, setOpen] = useState(false);
  const [secondaryView, setSecondaryView] = useState<SecondaryViewState | null>(
    null
  );
  const [searchTerm, setSearchTerm] = useState("");
  const [showFadeMask, setShowFadeMask] = useState(false);
  const [showTopShadow, setShowTopShadow] = useState(false);
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
  const {
    agentPreferences: assistantPreferences,
    setSpecificAgentPreferences: setSpecificAssistantPreferences,
    forcedToolIds,
    setForcedToolIds,
  } = useAgentsContext();

  const { isAdmin, isCurator } = useUser();

  const { availableTools, ccPairs } = useChatContext();
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

  // Simple and clean overflow detection
  const checkScrollState = useCallback((element: HTMLElement) => {
    const hasOverflow = element.scrollHeight > element.clientHeight;
    const isAtBottom =
      element.scrollHeight - element.scrollTop - element.clientHeight <= 1;
    const isAtTop = element.scrollTop <= 1;

    const shouldShowBottomMask = hasOverflow && !isAtBottom;
    const shouldShowTopShadow = hasOverflow && !isAtTop;

    setShowFadeMask(shouldShowBottomMask);
    setShowTopShadow(shouldShowTopShadow);
  }, []);

  // Check scroll state when entering secondary views
  useEffect(() => {
    if (!secondaryView) {
      setShowFadeMask(false);
      setShowTopShadow(false);
    }
  }, [secondaryView]);

  // Filter out MCP tools from the main list (they have mcp_server_id)
  // and filter out tools that are not available
  // Also filter out internal search tool for basic users when there are no connectors
  const displayTools = selectedAssistant.tools.filter((tool) => {
    // Filter out MCP tools
    if (tool.mcp_server_id) return false;

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
    const fetchMCPServers = async () => {
      if (selectedAssistant == null || selectedAssistant.id == null) return;

      try {
        const response = await fetch(
          `/api/mcp/servers/persona/${selectedAssistant.id}`
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
        console.error("Error fetching MCP servers:", error);
      }
    };

    fetchMCPServers();
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

  const mcpToggleItems: ToggleListItem[] = selectedMcpTools.map((tool) => ({
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

  const mcpFooter = showActiveReauthRow ? (
    <div className="sticky bottom-0 bg-background-neutral-00 border-t border-border z-[1] rounded-b-lg">
      <div
        role="button"
        tabIndex={0}
        className="
          w-full
          flex
          items-center
          justify-between
          px-2
          py-2.5
          text-left
          bg-background-neutral-00
          hover:bg-background-neutral-01
          rounded-b-lg
          hover:rounded-b-lg
          transition-colors
          cursor-pointer
        "
        onClick={handleFooterReauthClick}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            handleFooterReauthClick();
          }
        }}
      >
        <div className="flex items-center gap-2">
          {selectedMcpServerData?.isLoading ? (
            <FiLoader className="animate-spin text-text-02" size={14} />
          ) : (
            <IconButton
              icon={SvgKey}
              internal
              aria-label="Re-Authenticate"
              onClick={(event) => {
                event.stopPropagation();
                handleFooterReauthClick();
              }}
            />
          )}
          <span className="text-sm font-medium text-text-04">
            Re-Authenticate
          </span>
        </div>
        {!selectedMcpServerData?.isLoading && (
          <SvgChevronRight
            width={14}
            height={14}
            className="stroke-text-02 transition-colors"
          />
        )}
      </div>
    </div>
  ) : undefined;

  const configuredSources = getConfiguredSources(availableSources);

  const sourceToggleItems: ToggleListItem[] = configuredSources.map(
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

  // If no tools or MCP servers are available, don't render the component
  if (displayTools.length === 0 && mcpServers.length === 0) {
    return null;
  }
  return (
    <>
      <Popover
        open={open}
        onOpenChange={(newOpen) => {
          setOpen(newOpen);
          // Clear search when closing
          if (!newOpen) {
            setSearchTerm("");
            setSecondaryView(null);
            setShowFadeMask(false);
            setShowTopShadow(false);
          }
        }}
      >
        <PopoverTrigger asChild>
          <div>
            <IconButton
              icon={SvgSliders}
              tertiary
              data-testid="action-management-toggle"
              tooltip="Manage Actions"
            />
          </div>
        </PopoverTrigger>
        <PopoverContent
          data-testid="tool-options"
          side="top"
          align="start"
          className="
            w-[15.5rem] 
            max-h-[300px]
            text-text-03
            text-sm 
            p-0 
            overflow-hidden
            flex
            flex-col
            border border-border
            shadow-lg
          "
          style={{
            borderRadius: "var(--Radius-12, 12px)",
          }}
        >
          {/* Search Input */}
          {!secondaryView && (
            <div className="pt-1 mx-2">
              <InputTypeIn
                placeholder="Search Menu"
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                autoFocus
                internal
              />
            </div>
          )}

          {/* Options */}
          <div className="flex flex-col overflow-hidden">
            {secondaryView?.type === "sources" ? (
              <ToggleList
                items={sourceToggleItems}
                searchPlaceholder="Search Filters"
                allDisabled={allSourcesDisabled}
                onDisableAll={disableAllSources}
                onEnableAll={enableAllSources}
                disableAllLabel="Disable All Sources"
                enableAllLabel="Enable All Sources"
                noResultsText="No matching sources found"
                noItemsText="No configured sources found"
                onBack={() => setSecondaryView(null)}
                onScrollStateChange={checkScrollState}
                showTopShadow={showTopShadow}
                showFadeMask={showFadeMask}
              />
            ) : secondaryView?.type === "mcp" ? (
              <ToggleList
                items={mcpToggleItems}
                searchPlaceholder={`Search ${
                  selectedMcpServer?.name ?? "server"
                } tools`}
                allDisabled={mcpAllDisabled}
                onDisableAll={disableAllToolsForSelectedServer}
                onEnableAll={enableAllToolsForSelectedServer}
                disableAllLabel="Disable All Tools"
                enableAllLabel="Enable All Tools"
                noResultsText="No matching tools found"
                noItemsText="No tools available"
                onBack={() => setSecondaryView(null)}
                onScrollStateChange={checkScrollState}
                showTopShadow={showTopShadow}
                showFadeMask={showFadeMask}
                footer={mcpFooter}
              />
            ) : filteredTools.length === 0 &&
              filteredMCPServers.length === 0 ? (
              <div className="text-center py-1 text-text-02">
                No matching actions found
              </div>
            ) : (
              <>
                {/* Regular Tools */}
                {filteredTools.map((tool) => (
                  <ActionItem
                    key={tool.id}
                    tool={tool}
                    disabled={disabledToolIds.includes(tool.id)}
                    isForced={forcedToolIds.includes(tool.id)}
                    onToggle={() => toggleToolForCurrentAssistant(tool.id)}
                    onForceToggle={() => {
                      toggleForcedTool(tool.id);
                      setOpen(false);
                    }}
                    onSourceManagementOpen={() =>
                      setSecondaryView({ type: "sources" })
                    }
                    hasNoConnectors={hasNoConnectors}
                    toolAuthStatus={getToolAuthStatus(tool)}
                    onOAuthAuthenticate={() => authenticateTool(tool)}
                  />
                ))}

                {/* MCP Servers */}
                {filteredMCPServers.map((server) => {
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
                    <MCPServerItem
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
                })}
                {/* More Connectors & Actions. Only show if user is admin or curator, since
                they are the only ones who can manage actions. */}
                {(isAdmin || isCurator) && (
                  <>
                    <div className="border-b border-border mx-3.5 mt-2" />
                    <div className="mx-2 mt-2.5 mb-2">
                      <Button
                        defaulted
                        tertiary
                        href="/admin/actions"
                        leftIcon={MoreActionsIcon}
                        className="w-full justify-start"
                      >
                        More Actions
                      </Button>
                    </div>
                  </>
                )}
              </>
            )}
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
