"use client";

import {
  SlidersVerticalIcon,
  SearchIcon,
  DisableIcon,
  IconProps,
  MoreActionsIcon,
} from "@/components/icons/icons";
import React, { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import {
  ToolSnapshot,
  MCPAuthenticationType,
  MCPAuthenticationPerformer,
} from "@/lib/tools/interfaces";
import { useAssistantsContext } from "@/components/context/AssistantsContext";
import Link from "next/link";
import { getIconForAction } from "../../services/actionUtils";
import { useUser } from "@/components/user/UserProvider";
import {
  FiServer,
  FiChevronRight,
  FiKey,
  FiLock,
  FiCheck,
  FiAlertTriangle,
  FiLoader,
} from "react-icons/fi";
import { MCPApiKeyModal } from "@/components/chat/MCPApiKeyModal";

interface ActionItemProps {
  tool?: ToolSnapshot;
  Icon?: (iconProps: IconProps) => JSX.Element;
  label?: string;
  disabled: boolean;
  isForced: boolean;
  onToggle: () => void;
  onForceToggle: () => void;
}

export function ActionItem({
  tool,
  Icon: ProvidedIcon,
  label: providedLabel,
  disabled,
  isForced,
  onToggle,
  onForceToggle,
}: ActionItemProps) {
  // If a tool is provided, derive the icon and label from it
  const Icon = tool ? getIconForAction(tool) : ProvidedIcon!;
  const label = tool ? tool.display_name || tool.name : providedLabel!;
  return (
    <div
      className={`
      group
      flex 
      items-center 
      justify-between 
      px-2 
      cursor-pointer 
      hover:bg-background-100 
      dark:hover:bg-neutral-800
      dark:text-neutral-300
      rounded-lg 
      py-2 
      mx-1
      ${isForced ? "bg-accent-100 hover:bg-accent-200" : ""}
    `}
      onClick={() => {
        // If disabled, un-disable the tool
        if (onToggle && disabled) {
          onToggle();
        }

        onForceToggle();
      }}
    >
      <div
        className={`flex items-center gap-2 flex-1 ${
          disabled ? "opacity-50" : ""
        } ${isForced && "text-blue-500"}`}
      >
        <Icon
          size={16}
          className={
            isForced ? "text-blue-500" : "text-text-500 dark:text-neutral-400"
          }
        />
        <span
          className={`text-sm font-medium select-none ${
            disabled ? "line-through" : ""
          }`}
        >
          {label}
        </span>
      </div>
      <div
        className={`
          flex
          items-center
          gap-2
          transition-opacity
          duration-200
          ${disabled ? "opacity-100" : "opacity-0 group-hover:opacity-100"}
        `}
        onClick={(e) => {
          e.stopPropagation();
          onToggle();
        }}
      >
        <DisableIcon
          className={`transition-colors cursor-pointer ${
            disabled
              ? "text-text-900 hover:text-text-500"
              : "text-text-500 hover:text-text-900"
          }`}
        />
      </div>
    </div>
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

interface MCPTool {
  name: string;
  display_name?: string;
  description?: string;
  parameters?: any;
}

interface MCPServerItemProps {
  server: MCPServer;
  isExpanded: boolean;
  onToggleExpand: (element: HTMLElement) => void;
  onAuthenticate: () => void;
  tools: ToolSnapshot[];
  isAuthenticated: boolean;
  isLoading: boolean;
}

function MCPServerItem({
  server,
  isExpanded,
  onToggleExpand,
  onAuthenticate,
  tools,
  isAuthenticated,
  isLoading,
}: MCPServerItemProps) {
  const itemRef = useRef<HTMLDivElement>(null);

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

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation(); // Prevent closing the main popup
    if (isAuthenticated && itemRef.current) {
      console.log("MCPServerItem handleClick - passing element:", {
        element: itemRef.current,
        rect: itemRef.current.getBoundingClientRect(),
        tagName: itemRef.current.tagName,
        classes: itemRef.current.className,
      });
      onToggleExpand(itemRef.current);
    } else if (!isAuthenticated) {
      onAuthenticate();
    }
  };

  return (
    <div
      ref={itemRef}
      className={`
        group
        flex 
        items-center 
        justify-between 
        px-2 
        cursor-pointer 
        hover:bg-background-100 
        dark:hover:bg-neutral-800
        dark:text-neutral-300
        rounded-lg 
        py-2 
        mx-1
        ${isExpanded ? "bg-accent-100 hover:bg-accent-200" : ""}
      `}
      onClick={handleClick}
      data-mcp-server-id={server.id}
      data-mcp-server-name={server.name}
    >
      <div className="flex items-center gap-2 flex-1">
        {getServerIcon()}
        <span className="text-sm font-medium select-none">{server.name}</span>
        {isAuthenticated && tools.length > 0 && (
          <span className="text-xs text-text-400">({tools.length} tools)</span>
        )}
      </div>
      {isAuthenticated && tools.length > 0 && (
        <FiChevronRight
          className={`transition-transform ${isExpanded ? "rotate-90" : ""}`}
          size={14}
        />
      )}
    </div>
  );
}

interface MCPToolsListProps {
  tools: ToolSnapshot[];
  serverName: string;
  onClose: () => void;
  selectedAssistant: MinimalPersonaSnapshot;
  preventMainPopupClose: () => void;
}

function MCPToolsList({
  tools,
  serverName,
  onClose,
  selectedAssistant,
  preventMainPopupClose,
}: MCPToolsListProps) {
  console.log("MCPToolsList", tools, serverName, onClose, selectedAssistant);
  const [searchTerm, setSearchTerm] = useState("");
  console.log("searchTerm", searchTerm);
  const {
    assistantPreferences,
    setSpecificAssistantPreferences,
    forcedToolIds,
    setForcedToolIds,
  } = useAssistantsContext();

  console.log("assistantPreferences", assistantPreferences);
  const assistantPreference = assistantPreferences?.[selectedAssistant.id];
  const disabledToolIds = assistantPreference?.disabled_tool_ids || [];

  const toggleToolForCurrentAssistant = (toolId: number) => {
    const disabled = disabledToolIds.includes(toolId);
    setSpecificAssistantPreferences(selectedAssistant.id, {
      disabled_tool_ids: disabled
        ? disabledToolIds.filter((id) => id !== toolId)
        : [...disabledToolIds, toolId],
    });
  };

  const toggleForcedTool = (toolId: number) => {
    // Keep both popovers open; only outside clicks should close
    preventMainPopupClose();
    if (forcedToolIds.includes(toolId)) {
      setForcedToolIds([]);
    } else {
      setForcedToolIds([toolId]);
    }
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

  console.log("filteredTools2", filteredTools);
  return (
    <div
      className="
        w-[244px] 
        max-h-[300px]
        text-text-600 
        text-sm 
        p-0 
        bg-background 
        border 
        border-border 
        rounded-xl 
        shadow-xl 
        overflow-hidden
        flex
        flex-col
      "
      onClick={(e) => e.stopPropagation()}
    >
      {/* Search Input */}
      <div className="pt-1 mx-1">
        <div className="relative">
          <SearchIcon
            size={16}
            className="absolute left-3 top-1/2 transform -translate-y-1/2 text-text-400"
          />
          <input
            type="text"
            placeholder={`Search ${serverName} tools`}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="
              w-full 
              pl-9 
              pr-3 
              py-2 
              bg-background-50 
              rounded-lg 
              text-sm 
              outline-none 
              text-text-700
              placeholder:text-text-400
              dark:placeholder:text-neutral-600
              dark:bg-neutral-950
            "
            autoFocus
          />
        </div>
      </div>

      {/* Tools List */}
      <div className="pt-2 flex-1 overflow-y-auto mx-1 pb-2">
        {filteredTools.length === 0 ? (
          <div className="text-center py-1 text-text-400">
            No matching tools found
          </div>
        ) : (
          filteredTools.map((tool) => (
            <ActionItem
              key={tool.id}
              tool={tool}
              disabled={disabledToolIds.includes(tool.id)}
              isForced={forcedToolIds.includes(tool.id)}
              onToggle={() => toggleToolForCurrentAssistant(tool.id)}
              onForceToggle={() => toggleForcedTool(tool.id)}
            />
          ))
        )}
      </div>
    </div>
  );
}

interface ActionToggleProps {
  selectedAssistant: MinimalPersonaSnapshot;
}

export function ActionToggle({ selectedAssistant }: ActionToggleProps) {
  const [open, setOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [mcpServers, setMcpServers] = useState<MCPServer[]>([]);
  const [mcpToolsPopup, setMcpToolsPopup] = useState<{
    serverId: number | null;
    serverName: string;
    anchorElement: HTMLElement | null;
  }>({ serverId: null, serverName: "", anchorElement: null });

  // Track if we're in the process of opening an MCP popup
  const [isOpeningMcpPopup, setIsOpeningMcpPopup] = useState(false);
  const preventCloseRef = useRef(false);

  // Debug logging
  console.log(
    "ActionToggle render - open:",
    open,
    "mcpToolsPopup.serverId:",
    mcpToolsPopup.serverId
  );

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
    assistantPreferences,
    setSpecificAssistantPreferences,
    forcedToolIds,
    setForcedToolIds,
  } = useAssistantsContext();

  const { isAdmin, isCurator, user } = useUser();

  const assistantPreference = assistantPreferences?.[selectedAssistant.id];
  const disabledToolIds = assistantPreference?.disabled_tool_ids || [];
  const toggleToolForCurrentAssistant = (toolId: number) => {
    const disabled = disabledToolIds.includes(toolId);
    setSpecificAssistantPreferences(selectedAssistant.id, {
      disabled_tool_ids: disabled
        ? disabledToolIds.filter((id) => id !== toolId)
        : [...disabledToolIds, toolId],
    });
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
  const displayTools = selectedAssistant.tools.filter(
    (tool) => !tool.mcp_server_id
  );

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

  // Handle clicking outside MCP tools popup
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (mcpToolsPopup.serverId && mcpToolsPopup.anchorElement) {
        const target = event.target as Node;
        const mcpPopupElement = document.querySelector(
          '[data-mcp-popup="true"]'
        );

        // If click is not on the anchor element or inside the MCP popup, close it
        if (
          !mcpToolsPopup.anchorElement.contains(target) &&
          (!mcpPopupElement || !mcpPopupElement.contains(target))
        ) {
          console.log("Closing MCP popup due to outside click");
          setMcpToolsPopup({
            serverId: null,
            serverName: "",
            anchorElement: null,
          });
        }
      }
    };

    if (mcpToolsPopup.serverId) {
      document.addEventListener("mousedown", handleClickOutside);
      return () =>
        document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [mcpToolsPopup.serverId, mcpToolsPopup.anchorElement]);

  // Handle MCP authentication
  const handleMCPAuthenticate = async (
    serverId: number,
    authType: MCPAuthenticationType
  ) => {
    if (authType === MCPAuthenticationType.OAUTH) {
      try {
        const response = await fetch("/api/mcp/oauth/initiate", {
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
        }
      } catch (error) {
        console.error("Error initiating OAuth:", error);
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

  // If no tools or MCP servers are available, don't render the component
  if (displayTools.length === 0 && mcpServers.length === 0) {
    return null;
  }
  return (
    <>
      <Popover
        open={open}
        onOpenChange={(newOpen) => {
          console.log(
            "Popover onOpenChange",
            newOpen,
            "preventCloseRef.current",
            preventCloseRef.current
          );

          // If we're trying to close but we should prevent it, don't close
          if (!newOpen && preventCloseRef.current) {
            console.log("Preventing popover close due to preventCloseRef");
            preventCloseRef.current = false; // Reset the flag
            return;
          }

          setOpen(newOpen);
          // Clear search when closing
          if (!newOpen) {
            setSearchTerm("");
            setMcpToolsPopup({
              serverId: null,
              serverName: "",
              anchorElement: null,
            }); // Close expanded MCP server
          }
        }}
      >
        <PopoverTrigger asChild>
          <button
            type="button"
            className="
            relative 
            cursor-pointer 
            flex 
            items-center 
            group 
            rounded-lg 
            text-input-text 
            hover:bg-background-chat-hover 
            hover:text-neutral-900 
            dark:hover:text-neutral-50
            py-1.5 
            px-2 
            flex-none 
            whitespace-nowrap 
            overflow-hidden 
            focus:outline-none
          "
            data-testid="action-popover-trigger"
            title={open ? undefined : "Configure actions"}
          >
            <SlidersVerticalIcon size={16} className="my-auto flex-none" />
          </button>
        </PopoverTrigger>
        <PopoverContent
          side="top"
          align="start"
          // Keep main popover open when interacting with nested MCP popup
          onPointerDownOutside={(e) => {
            const target = e.target as Node | null;
            const mcpPopup = document.querySelector('[data-mcp-popup="true"]');
            if (target && mcpPopup && mcpPopup.contains(target)) {
              // Prevent Radix from closing and set guard
              preventCloseRef.current = true;
              e.preventDefault();
            }
          }}
          onFocusOutside={(e) => {
            const target = e.target as Node | null;
            const mcpPopup = document.querySelector('[data-mcp-popup="true"]');
            if (target && mcpPopup && mcpPopup.contains(target)) {
              preventCloseRef.current = true;
              e.preventDefault();
            }
          }}
          className="
          w-[244px] 
          max-h-[300px]
          text-text-600 
          text-sm 
          p-0 
          bg-background 
          border 
          border-border 
          rounded-xl 
          shadow-xl 
          overflow-hidden
          flex
          flex-col
        "
        >
          {/* Search Input */}
          <div className="pt-1 mx-1">
            <div className="relative">
              <SearchIcon
                size={16}
                className="absolute left-3 top-1/2 transform -translate-y-1/2 text-text-400"
              />
              <input
                type="text"
                placeholder="Search Menu"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="
                w-full 
                pl-9 
                pr-3 
                py-2 
                bg-background-50 
                rounded-lg 
                text-sm 
                outline-none 
                text-text-700
                placeholder:text-text-400
                dark:placeholder:text-neutral-600
                dark:bg-neutral-950
              "
                autoFocus
              />
            </div>
          </div>

          {/* Options */}
          <div className="pt-2 flex-1 overflow-y-auto mx-1 pb-2 relative">
            {filteredTools.length === 0 && filteredMCPServers.length === 0 ? (
              <div className="text-center py-1 text-text-400">
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

                  return (
                    <MCPServerItem
                      key={server.id}
                      server={server}
                      isExpanded={mcpToolsPopup.serverId === server.id}
                      tools={serverTools}
                      isAuthenticated={serverData.isAuthenticated}
                      isLoading={serverData.isLoading}
                      onToggleExpand={(element: HTMLElement) => {
                        const serverName = element.getAttribute(
                          "data-mcp-server-name"
                        );
                        console.log(
                          "onToggleExpand called",
                          server.id,
                          mcpToolsPopup.serverId
                        );

                        if (mcpToolsPopup.serverId === server.id) {
                          // Close if already open
                          console.log("Closing MCP popup");
                          setMcpToolsPopup({
                            serverId: null,
                            serverName: "",
                            anchorElement: null,
                          });
                        } else {
                          // Set flag to prevent popover from closing
                          console.log("Setting preventCloseRef to true");
                          preventCloseRef.current = true;

                          console.log(
                            "Opening MCP popup",
                            server.id,
                            serverName
                          );
                          setMcpToolsPopup({
                            serverId: server.id,
                            serverName: serverName || server.name,
                            anchorElement: element,
                          });
                        }
                      }}
                      onAuthenticate={() => handleServerAuthentication(server)}
                    />
                  );
                })}
              </>
            )}
          </div>

          <div className="border-b border-border mx-3.5" />

          {/* More Connectors & Actions. Only show if user is admin or curator, since
        they are the only ones who can manage actions. */}
          {(isAdmin || isCurator) && (
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
                  hover:bg-background-100
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
          )}
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

      {/* MCP Tools Popup */}
      {mcpToolsPopup.serverId !== null &&
        mcpToolsPopup.anchorElement &&
        (() => {
          const rect = mcpToolsPopup.anchorElement.getBoundingClientRect();
          // Anchor the popup to the server element using viewport coordinates
          const positioning = {
            position: "fixed" as const,
            left: rect.right + 8,
            top: rect.top,
            zIndex: 1000,
          };

          return createPortal(
            <div
              style={positioning}
              onClick={(e) => e.stopPropagation()}
              onMouseDownCapture={() => {
                preventCloseRef.current = true;
              }}
              onPointerDownCapture={() => {
                preventCloseRef.current = true;
              }}
              data-mcp-popup="true"
            >
              <MCPToolsList
                tools={selectedAssistant.tools.filter(
                  (t) => t.mcp_server_id === Number(mcpToolsPopup.serverId)
                )}
                serverName={mcpToolsPopup.serverName}
                onClose={() =>
                  setMcpToolsPopup({
                    serverId: null,
                    serverName: "",
                    anchorElement: null,
                  })
                }
                selectedAssistant={selectedAssistant}
                preventMainPopupClose={() => {
                  preventCloseRef.current = true;
                }}
              />
            </div>,
            document.body
          );
        })()}
    </>
  );
}
