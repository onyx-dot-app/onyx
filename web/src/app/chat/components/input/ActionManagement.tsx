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
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import {
  ToolSnapshot,
  MCPAuthenticationType,
  MCPAuthenticationPerformer,
} from "@/lib/tools/interfaces";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";
import Link from "next/link";
import { getIconForAction } from "../../services/actionUtils";
import { useUser } from "@/components/user/UserProvider";
import { FilterManager, useSourcePreferences } from "@/lib/hooks";
import { listSourceMetadata } from "@/lib/sources";
import {
  FiServer,
  FiChevronRight,
  FiChevronLeft,
  FiKey,
  FiLock,
  FiCheck,
  FiLoader,
  FiSettings,
} from "react-icons/fi";
import { MCPApiKeyModal } from "@/components/chat/MCPApiKeyModal";
import { ValidSources } from "@/lib/types";
import { SourceMetadata } from "@/lib/search/interfaces";
import { SourceIcon } from "@/components/SourceIcon";
import { useChatContext } from "@/refresh-components/contexts/ChatContext";
import { useTheme } from "next-themes";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgSliders from "@/icons/sliders";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { cn } from "@/lib/utils";

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
            className={`
            group
            flex
            items-center
            justify-between
            px-2
            cursor-pointer
            hover:bg-neutral-100
            dark:hover:bg-neutral-800
            dark:text-neutral-300
            rounded-lg
            py-2
            mx-1
            ${isForced ? "bg-accent-100 hover:bg-accent-200" : ""}
          `}
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
              className={`flex items-center gap-2 flex-1 ${
                isSearchToolWithNoConnectors || disabled ? "opacity-50" : ""
              } ${isForced && "text-blue-500"}`}
            >
              <Icon
                className={cn(
                  "h-[1rem] w-[1rem] stroke-text-04",
                  isForced
                    ? "text-blue-500"
                    : "text-text-500 dark:text-neutral-400"
                )}
              />
              <span
                className={`text-sm font-medium select-none ${
                  isSearchToolWithNoConnectors || disabled ? "line-through" : ""
                }`}
              >
                {label}
              </span>
            </div>
            <div className="flex items-center gap-2">
              {!isSearchToolWithNoConnectors && (
                <div
                  className={`
                    flex
                    items-center
                    gap-2
                    transition-opacity
                    duration-200
                    ${
                      disabled
                        ? "opacity-100"
                        : "opacity-0 group-hover:opacity-100"
                    }
                  `}
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggle();
                  }}
                >
                  <DisableIcon
                    className={`transition-colors cursor-pointer ${
                      disabled
                        ? "text-neutral-900 dark:text-neutral-100 hover:text-neutral-500 dark:hover:text-neutral-400"
                        : "text-neutral-500 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-100"
                    }`}
                  />
                </div>
              )}
              {tool && tool.in_code_tool_id === SEARCH_TOOL_ID && (
                <div
                  className={`
                    flex
                    items-center
                    gap-2
                    transition-opacity
                    duration-200
                    ${
                      isSearchToolWithNoConnectors
                        ? "opacity-0 group-hover:opacity-100"
                        : ""
                    }
                  `}
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
                    <FiSettings
                      size={16}
                      className="transition-colors cursor-pointer text-neutral-500 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-100"
                    />
                  ) : (
                    <FiChevronRight
                      size={16}
                      className="transition-colors cursor-pointer text-neutral-500 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-100"
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
      return <FiCheck className="text-green-500" />;
    }
    if (server.auth_type === MCPAuthenticationType.NONE) {
      return <FiServer />;
    }
    if (server.auth_performer === MCPAuthenticationPerformer.PER_USER) {
      return <FiKey className="text-yellow-500" />;
    }
    return <FiLock className="text-red-500" />;
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
      className={`
        group
        flex
        items-center
        justify-between
        px-2
        cursor-pointer
        hover:bg-neutral-100
        dark:hover:bg-neutral-800
        dark:text-neutral-300
        rounded-lg
        py-2
        mx-1
        ${isActive ? "bg-accent-100 hover:bg-accent-200" : ""}
        ${allToolsDisabled ? "opacity-60" : ""}
      `}
      onClick={handleClick}
      data-mcp-server-id={server.id}
      data-mcp-server-name={server.name}
    >
      <div className="flex items-center gap-2 flex-1">
        {getServerIcon()}
        <span
          className={`text-sm font-medium select-none truncate max-w-[120px] inline-block align-middle ${
            allToolsDisabled ? "line-through" : ""
          }`}
          title={server.name}
        >
          {server.name}
        </span>
        {isAuthenticated &&
          tools.length > 0 &&
          enabledTools.length > 0 &&
          tools.length !== enabledTools.length && (
            <span className="text-xs whitespace-nowrap ml-1 text-neutral-400 dark:text-neutral-500">
              <span className="text-blue-500">{enabledTools.length}</span>
              {` of ${tools.length}`}
            </span>
          )}
      </div>
      <div className="flex items-center gap-1">
        {showReauthButton && (
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onAuthenticate();
            }}
            className="p-1 text-neutral-500 hover:text-neutral-900 hover:bg-background-200 dark:text-neutral-400 dark:hover:text-neutral-100 dark:hover:bg-neutral-700 rounded-md transition-colors"
            aria-label="Re-authenticate MCP server"
            title="Re-authenticate"
          >
            <FiKey size={14} />
          </button>
        )}
        {isAuthenticated && tools.length > 0 && (
          <FiChevronRight
            className={`transition-transform ${isActive ? "rotate-90" : ""}`}
            size={14}
          />
        )}
      </div>
    </div>
  );
}

interface MCPToolsListProps {
  tools: ToolSnapshot[];
  serverName: string;
  selectedAssistant: MinimalPersonaSnapshot;
  onBack: () => void;
  onShowSourceManagement?: () => void;
  onScrollStateChange: (element: HTMLElement) => void;
  showTopShadow: boolean;
  showFadeMask: boolean;
  showReauthRow?: boolean;
  onReauthenticate?: () => void;
  isReauthLoading?: boolean;
}

function MCPToolsList({
  tools,
  serverName,
  selectedAssistant,
  onBack,
  onShowSourceManagement,
  onScrollStateChange,
  showTopShadow,
  showFadeMask,
  showReauthRow = false,
  onReauthenticate,
  isReauthLoading = false,
}: MCPToolsListProps) {
  const [searchTerm, setSearchTerm] = useState("");
  const {
    agentPreferences: assistantPreferences,
    setSpecificAgentPreferences: setSpecificAssistantPreferences,
    forcedToolIds,
    setForcedToolIds,
  } = useAgentsContext();
  const { theme } = useTheme();

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

  const serverToolIds = tools.map((tool) => tool.id);
  const allToolsDisabled = tools.every((tool) =>
    disabledToolIds.includes(tool.id)
  );

  const disableAllToolsForServer = () => {
    const merged = Array.from(new Set([...disabledToolIds, ...serverToolIds]));
    setSpecificAssistantPreferences(selectedAssistant.id, {
      disabled_tool_ids: merged,
    });
    setForcedToolIds(forcedToolIds.filter((id) => !serverToolIds.includes(id)));
  };

  const enableAllToolsForServer = () => {
    const serverToolIdSet = new Set(serverToolIds);
    setSpecificAssistantPreferences(selectedAssistant.id, {
      disabled_tool_ids: disabledToolIds.filter(
        (id) => !serverToolIdSet.has(id)
      ),
    });
  };

  // Filter tools based on search
  const filteredTools = tools.filter((tool) => {
    if (!searchTerm) return true;
    const searchLower = searchTerm.toLowerCase();
    return (
      tool.display_name?.toLowerCase().includes(searchLower) ||
      tool.name.toLowerCase().includes(searchLower) ||
      tool.description?.toLowerCase().includes(searchLower)
    );
  });

  useEffect(() => {
    const timer = setTimeout(() => {
      const element = document.getElementById(
        "action-submenu-scroll"
      ) as HTMLElement | null;
      if (element) {
        onScrollStateChange(element);
      }
    }, 50);

    return () => clearTimeout(timer);
  }, [searchTerm, tools, onScrollStateChange]);

  const placeholderName = serverName || "server";

  return (
    <>
      <div className="bg-transparent flex-shrink-0">
        <div className="mx-1">
          <div className="relative">
            <button
              onClick={() => {
                setSearchTerm("");
                onBack();
              }}
              className="absolute left-1 top-1/2 transform -translate-y-1/2 text-text-400 hover:text-text-300 z-10 w-4 h-4 flex items-center justify-center transition-colors"
              style={{ borderRadius: "8px" }}
              aria-label="Back to action menu"
            >
              <FiChevronLeft size={16} />
            </button>
            <input
              type="text"
              placeholder={`Search ${placeholderName} tools`}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="
                w-full
                pl-7
                pr-3
                py-2
                bg-transparent
                rounded-lg
                text-sm
                outline-none
                text-neutral-700 dark:text-neutral-300
                placeholder:text-neutral-400 dark:placeholder:text-neutral-500
              "
              autoFocus
            />
          </div>
        </div>
        <div className="mx-1">
          <div className="relative mt-1">
            <input
              type="text"
              placeholder={
                allToolsDisabled ? "Enable All Tools" : "Disable All Tools"
              }
              readOnly
              onClick={
                allToolsDisabled
                  ? enableAllToolsForServer
                  : disableAllToolsForServer
              }
              className="
                w-full
                pl-7
                pr-9
                py-2
                bg-transparent
                rounded-lg
                text-sm
                outline-none
                text-neutral-700 dark:text-neutral-300
                placeholder:text-neutral-400 dark:placeholder:text-neutral-500
                cursor-pointer
              "
            />
            <img
              src={allToolsDisabled ? "/plug.svg" : "/unplug.svg"}
              alt={allToolsDisabled ? "Enable All Tools" : "Disable All Tools"}
              className="absolute right-3 top-1/2 transform -translate-y-1/2 w-4 h-4 pointer-events-none"
              style={{
                filter:
                  theme === "dark"
                    ? "invert(0.6) sepia(1) saturate(0) hue-rotate(0deg) brightness(1.2)"
                    : "invert(0.6) sepia(1) saturate(0) hue-rotate(0deg) brightness(0.6)",
                opacity: theme === "dark" ? 0.9 : 0.8,
              }}
            />
          </div>
        </div>
        <div className="border-b border-border mx-1 mt-1" />
        <div
          className="mx-1 h-2 -mb-2 transition-opacity ease-out"
          style={{
            background:
              "linear-gradient(to bottom, rgba(0, 0, 0, 0.06), transparent)",
            opacity: showTopShadow ? 1 : 0,
          }}
        />
      </div>

      <div
        id="action-submenu-scroll"
        className="flex-1 overflow-y-auto min-h-0 relative"
        onScroll={(e) => onScrollStateChange(e.currentTarget)}
      >
        <div className="space-y-1.5 pb-2 pt-2">
          {filteredTools.length === 0 ? (
            <div className="text-center py-4 text-neutral-400 dark:text-neutral-500">
              No matching tools found
            </div>
          ) : (
            filteredTools.map((tool) => {
              const isDisabled = disabledToolIds.includes(tool.id);
              const isEnabled = !isDisabled;

              const label = (
                <div className="flex flex-col cursor-default">
                  <span
                    className={`text-sm font-medium ${
                      isEnabled
                        ? "text-neutral-700 dark:text-neutral-200"
                        : "text-neutral-400 dark:text-neutral-500"
                    }`}
                  >
                    {tool.display_name || tool.name}
                  </span>
                </div>
              );

              return (
                <div
                  key={tool.id}
                  className="flex items-center justify-between px-2 py-1.5 mx-1 rounded-lg hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors"
                >
                  {tool.description ? (
                    <TooltipProvider delayDuration={600}>
                      <Tooltip>
                        <TooltipTrigger asChild>{label}</TooltipTrigger>
                        <TooltipContent
                          side="right"
                          align="start"
                          className="max-w-xs"
                        >
                          <Text inverted>{tool.description}</Text>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  ) : (
                    label
                  )}
                  <button
                    type="button"
                    onClick={() => {
                      toggleToolForCurrentAssistant(tool.id);
                      if (forcedToolIds.includes(tool.id)) {
                        setForcedToolIds(
                          forcedToolIds.filter((id) => id !== tool.id)
                        );
                      }
                    }}
                    className={`relative transition-colors ${
                      isEnabled
                        ? "bg-blue-500"
                        : "bg-neutral-300 dark:bg-neutral-700"
                    }`}
                    style={{
                      width: "28px",
                      height: "16px",
                      borderRadius: "var(--Radius-Round, 1000px)",
                    }}
                    aria-pressed={isEnabled}
                    aria-label={`Toggle ${tool.display_name || tool.name}`}
                  >
                    <div
                      className={`absolute top-[2px] left-[2px] h-[12px] w-[12px] rounded-full transition-transform duration-200 ease-in-out ${
                        isEnabled
                          ? "translate-x-[12px] bg-white"
                          : "translate-x-0 bg-white dark:bg-neutral-900"
                      }`}
                      style={{
                        boxShadow: "0 0 1px 1px rgba(0, 0, 0, 0.05)",
                      }}
                    />
                  </button>
                </div>
              );
            })
          )}
        </div>
        <div
          className="sticky w-full pointer-events-none transition-opacity ease-out bg-gradient-to-t from-white to-transparent dark:from-neutral-900"
          style={{
            bottom: showReauthRow ? "40px" : "0px",
            height: "24px",
            opacity: showFadeMask ? 1 : 0,
          }}
        />
        {showReauthRow && onReauthenticate && (
          <div className="sticky bottom-0 bg-background-neutral-00 border-t border-border z-[1] rounded-b-lg">
            <button
              type="button"
              onClick={onReauthenticate}
              className="
                w-full
                flex
                items-center
                justify-between
                px-2
                py-2.5
                text-left
                bg-background-neutral-00
                hover:bg-neutral-100
                dark:hover:bg-neutral-800
                rounded-b-lg
                hover:rounded-b-lg
                transition-colors
              "
            >
              <div className="flex items-center gap-2">
                {isReauthLoading ? (
                  <FiLoader
                    className="animate-spin text-text-400 dark:text-neutral-500"
                    size={14}
                  />
                ) : (
                  <FiKey
                    className="text-text-500 dark:text-neutral-300"
                    size={14}
                  />
                )}
                <span className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
                  Re-Authenticate
                </span>
              </div>
              {!isReauthLoading && (
                <FiChevronRight
                  size={14}
                  className="text-neutral-400 dark:text-neutral-500 transition-colors"
                />
              )}
            </button>
          </div>
        )}
      </div>
    </>
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
  const { theme } = useTheme();
  const [open, setOpen] = useState(false);
  const [secondaryView, setSecondaryView] = useState<SecondaryViewState | null>(
    null
  );
  const [searchTerm, setSearchTerm] = useState("");
  const [sourceSearchTerm, setSourceSearchTerm] = useState("");
  const [showFadeMask, setShowFadeMask] = useState(false);
  const [showTopShadow, setShowTopShadow] = useState(false);
  const { selectedSources, setSelectedSources } = filterManager;
  const [mcpServers, setMcpServers] = useState<MCPServer[]>([]);

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
    if (secondaryView) {
      const timer = setTimeout(() => {
        const scrollContainer = document.getElementById(
          "action-submenu-scroll"
        ) as HTMLElement | null;
        if (scrollContainer) {
          checkScrollState(scrollContainer);
        }
      }, 50);
      return () => clearTimeout(timer);
    }
    setShowFadeMask(false);
    setShowTopShadow(false);
  }, [secondaryView, sourceSearchTerm, checkScrollState]);

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
      if (!selectedAssistant?.id) return;

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

  const activeMcpServerId =
    secondaryView?.type === "mcp" ? secondaryView.serverId : null;
  const activeMcpServer = activeMcpServerId
    ? mcpServers.find((server) => server.id === activeMcpServerId)
    : undefined;
  const activeMcpTools =
    activeMcpServerId !== null
      ? selectedAssistant.tools.filter(
          (t) => t.mcp_server_id === Number(activeMcpServerId)
        )
      : [];
  const activeMcpServerData = activeMcpServer
    ? mcpServerData[activeMcpServer.id]
    : undefined;
  const isActiveServerAuthenticated =
    activeMcpServerData?.isAuthenticated ??
    !!(
      activeMcpServer?.user_authenticated || activeMcpServer?.is_authenticated
    );
  const showActiveReauthRow =
    !!activeMcpServer &&
    activeMcpTools.length > 0 &&
    activeMcpServer.auth_performer === MCPAuthenticationPerformer.PER_USER &&
    activeMcpServer.auth_type !== MCPAuthenticationType.NONE &&
    isActiveServerAuthenticated;

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
            setSourceSearchTerm("");
            setSecondaryView(null);
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
            text-neutral-600 dark:text-neutral-400
            text-sm 
            p-0 
            overflow-hidden
            flex
            flex-col
            border border-neutral-200 dark:border-transparent
            shadow-lg dark:shadow-xl dark:shadow-[0_0_8px_rgba(255,255,255,0.05)]
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
          <div className="pt-2 flex-1 flex flex-col mx-1 relative overflow-hidden">
            {secondaryView?.type === "sources" ? (
              <>
                {/* Fixed Header */}
                <div className="bg-transparent flex-shrink-0">
                  <div className="mx-1">
                    <div className="relative">
                      <button
                        onClick={() => {
                          setSecondaryView(null);
                          setSourceSearchTerm("");
                        }}
                        className="absolute left-1 top-1/2 transform -translate-y-1/2 text-text-400 hover:text-text-300 z-10 w-4 h-4 flex items-center justify-center transition-colors"
                        style={{ borderRadius: "8px" }}
                      >
                        <FiChevronLeft size={16} />
                      </button>
                      <input
                        type="text"
                        placeholder="Search Filters"
                        value={sourceSearchTerm}
                        onChange={(e) => setSourceSearchTerm(e.target.value)}
                        className="
                          w-full
                          pl-7
                          pr-3
                          py-2
                          bg-transparent
                          rounded-lg
                          text-sm
                          outline-none
                          text-neutral-700 dark:text-neutral-300
                          placeholder:text-neutral-400 dark:placeholder:text-neutral-500
                        "
                      />
                    </div>
                    {(() => {
                      const anyEnabled = selectedSources.length > 0;
                      if (anyEnabled) {
                        return (
                          <div className="relative mt-1">
                            <input
                              type="text"
                              placeholder="Disable All Sources"
                              readOnly
                              onClick={disableAllSources}
                              className="
                                w-full
                                pl-7
                                pr-9
                                py-2
                                bg-transparent
                                rounded-lg
                                text-sm
                                outline-none
                                text-neutral-700 dark:text-neutral-300
                                placeholder:text-neutral-400 dark:placeholder:text-neutral-500
                                cursor-pointer
                              "
                            />
                            <img
                              src="/unplug.svg"
                              alt="Disable All Sources"
                              className="absolute right-3 top-1/2 transform -translate-y-1/2 w-4 h-4 pointer-events-none"
                              style={{
                                filter:
                                  theme === "dark"
                                    ? "invert(0.6) sepia(1) saturate(0) hue-rotate(0deg) brightness(1.2)"
                                    : "invert(0.6) sepia(1) saturate(0) hue-rotate(0deg) brightness(0.6)",
                                opacity: theme === "dark" ? 0.9 : 0.8,
                              }}
                            />
                          </div>
                        );
                      } else {
                        return (
                          <div className="relative mt-1">
                            <input
                              type="text"
                              placeholder="Enable All Sources"
                              readOnly
                              onClick={enableAllSources}
                              className="
                                w-full
                                pl-7
                                pr-9
                                py-2
                                bg-transparent
                                rounded-lg
                                text-sm
                                outline-none
                                text-neutral-700 dark:text-neutral-300
                                placeholder:text-neutral-400 dark:placeholder:text-neutral-500
                                cursor-pointer
                              "
                            />
                            <img
                              src="/plug.svg"
                              alt="Enable All Sources"
                              className="absolute right-3 top-1/2 transform -translate-y-1/2 w-4 h-4 pointer-events-none"
                              style={{
                                filter:
                                  theme === "dark"
                                    ? "invert(0.6) sepia(1) saturate(0) hue-rotate(0deg) brightness(1.2)"
                                    : "invert(0.6) sepia(1) saturate(0) hue-rotate(0deg) brightness(0.6)",
                                opacity: theme === "dark" ? 0.9 : 0.8,
                              }}
                            />
                          </div>
                        );
                      }
                    })()}
                  </div>
                  {/* Separator line - always visible, full width like sources */}
                  <div className="border-b border-border mx-1 mt-1" />
                  {/* Shadow below separator - only when scrolled down */}
                  <div
                    className="mx-1 h-2 -mb-2 transition-opacity ease-out"
                    style={{
                      background:
                        "linear-gradient(to bottom, rgba(0, 0, 0, 0.06), transparent)",
                      opacity: showTopShadow ? 1 : 0,
                    }}
                  />
                </div>

                {/* Scrollable Content */}
                <div
                  id="action-submenu-scroll"
                  className="flex-1 overflow-y-auto min-h-0 relative"
                  onScroll={(e) => checkScrollState(e.currentTarget)}
                  onLoad={(e) => checkScrollState(e.currentTarget)}
                >
                  <div className="space-y-1.5 pb-2 pt-2">
                    {getConfiguredSources(availableSources)
                      .filter((source) => {
                        if (!sourceSearchTerm) return true;
                        const searchLower = sourceSearchTerm.toLowerCase();
                        return source.displayName
                          .toLowerCase()
                          .includes(searchLower);
                      })
                      .map((source) => (
                        <div
                          key={source.uniqueKey}
                          className="flex items-center justify-between px-1 py-1 mx-1 rounded-lg"
                        >
                          <div className="flex items-center gap-3">
                            <SourceIcon
                              sourceType={source.internalName}
                              iconSize={16}
                            />
                            <div>
                              <div
                                className={`text-sm font-medium ${
                                  isSourceEnabled(source.uniqueKey)
                                    ? "text-neutral-700 dark:text-neutral-300"
                                    : "text-neutral-400 dark:text-neutral-500"
                                }`}
                              >
                                {source.displayName}
                              </div>
                            </div>
                          </div>
                          <button
                            onClick={() => toggleSource(source.uniqueKey)}
                            className={`relative transition-colors ${
                              isSourceEnabled(source.uniqueKey)
                                ? "bg-blue-500"
                                : "bg-neutral-300 dark:bg-neutral-700"
                            }`}
                            style={{
                              width: "28px",
                              height: "16px",
                              borderRadius: "var(--Radius-Round, 1000px)",
                              transition: "background-color 0.2s ease-in-out",
                            }}
                          >
                            <div
                              className={`absolute transition-transform duration-200 ease-in-out ${
                                isSourceEnabled(source.uniqueKey)
                                  ? "bg-white"
                                  : "bg-white dark:bg-neutral-900"
                              }`}
                              style={{
                                width: "12px",
                                height: "12px",
                                borderRadius: "var(--Radius-Round, 1000px)",
                                boxShadow: "0 0 1px 1px rgba(0, 0, 0, 0.05)",
                                top: "2px",
                                left: "2px",
                                transform: isSourceEnabled(source.uniqueKey)
                                  ? "translateX(12px)"
                                  : "translateX(0px)",
                              }}
                            ></div>
                          </button>
                        </div>
                      ))}
                    {getConfiguredSources(availableSources).filter((source) => {
                      if (!sourceSearchTerm) return true;
                      const searchLower = sourceSearchTerm.toLowerCase();
                      return source.displayName
                        .toLowerCase()
                        .includes(searchLower);
                    }).length === 0 && (
                      <div className="text-center py-4 text-neutral-400 dark:text-neutral-500">
                        {sourceSearchTerm
                          ? "No matching sources found"
                          : "No configured sources found"}
                      </div>
                    )}
                  </div>
                </div>
                {/* Fade mask - only when content overflows and not at bottom */}
                <div
                  className="absolute bottom-0 left-0 right-0 h-6 pointer-events-none transition-opacity ease-out bg-gradient-to-t from-white to-transparent dark:from-neutral-900"
                  style={{
                    opacity: showFadeMask ? 1 : 0,
                  }}
                />
              </>
            ) : secondaryView?.type === "mcp" ? (
              <MCPToolsList
                tools={activeMcpTools}
                serverName={activeMcpServer?.name ?? ""}
                selectedAssistant={selectedAssistant}
                onBack={() => {
                  setSecondaryView(null);
                }}
                onShowSourceManagement={() =>
                  setSecondaryView({ type: "sources" })
                }
                onScrollStateChange={checkScrollState}
                showTopShadow={showTopShadow}
                showFadeMask={showFadeMask}
                showReauthRow={showActiveReauthRow}
                onReauthenticate={
                  activeMcpServer
                    ? () => handleServerAuthentication(activeMcpServer)
                    : undefined
                }
                isReauthLoading={activeMcpServerData?.isLoading ?? false}
              />
            ) : filteredTools.length === 0 &&
              filteredMCPServers.length === 0 ? (
              <div className="text-center py-1 text-neutral-400 dark:text-neutral-500">
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
                      isActive={activeMcpServerId === server.id}
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
                    <Link href="/admin/actions">
                      <button
                        className="
                        w-full
                        flex
                        items-center
                        justify-between
                        text-text-400
                        text-sm
                        mt-2.5
                      "
                      >
                        <div
                          className="
                          mx-2 
                          mb-2 
                          px-2 
                          py-1.5 
                          flex 
                          items-center 
                          text-text-500
                          dark:text-neutral-500
                          dark:hover:bg-neutral-800
                          hover:bg-neutral-100
                          hover:text-text-500
                          transition-colors
                          rounded-lg
                          w-full
                        "
                        >
                          <MoreActionsIcon className="text-text-500 dark:text-neutral-200" />
                          <div className="ml-2">More Actions</div>
                        </div>
                      </button>
                    </Link>
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
