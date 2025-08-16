"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  FiServer,
  FiChevronDown,
  FiKey,
  FiLock,
  FiCheck,
  FiAlertTriangle,
  FiLoader,
} from "react-icons/fi";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import {
  MinimalPersonaSnapshot,
  Persona,
} from "@/app/admin/assistants/interfaces";
import { usePopup } from "@/components/admin/connectors/Popup";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
} from "@/lib/tools/interfaces";

interface MCPAuthTemplate {
  headers: Array<{ name: string; value: string }>;
  request_body_params: Array<{ path: string; value: string }>;
  required_fields: string[];
}

interface MCPServer {
  id: string;
  name: string;
  server_url: string;
  auth_type: MCPAuthenticationType;
  auth_performer: MCPAuthenticationPerformer;
  is_authenticated: boolean;
  user_authenticated?: boolean; // For per-user auth
  auth_template?: MCPAuthTemplate;
  user_credentials?: Record<string, string>; // For pre-filling forms
}

interface MCPDropdownProps {
  selectedAssistant: MinimalPersonaSnapshot;
  onAuthenticateServer: (
    serverId: string,
    authType: MCPAuthenticationType
  ) => void;
  onOpenApiKeyModal: (
    serverId: string,
    serverName: string,
    authTemplate?: MCPAuthTemplate,
    onSuccess?: () => void,
    isAuthenticated?: boolean,
    existingCredentials?: Record<string, string>
  ) => void;
}

export function MCPDropdown({
  selectedAssistant,
  onAuthenticateServer,
  onOpenApiKeyModal,
}: MCPDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [mcpServers, setMcpServers] = useState<MCPServer[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasFetched, setHasFetched] = useState(false);
  const loadedAssistantIdRef = useRef<number | null>(null);
  const { popup, setPopup } = usePopup();

  // Fetch MCP servers for the selected assistant
  useEffect(() => {
    const assistantId = selectedAssistant?.id;

    // If no assistant selected, don't do anything
    if (!assistantId) {
      return;
    }

    // Don't refetch if we already have data for this assistant
    if (loadedAssistantIdRef.current === assistantId) {
      return;
    }

    const fetchMCPServers = async () => {
      try {
        setLoading(true);
        setHasFetched(false);
        const response = await fetch(`/api/mcp/servers/${assistantId}`);

        if (!response.ok) {
          throw new Error("Failed to fetch MCP servers");
        }

        const data = await response.json();
        setMcpServers(data.mcp_servers || []);
        loadedAssistantIdRef.current = assistantId;
      } catch (error) {
        console.error("Error fetching MCP servers:", error);
        setPopup({
          message: "Failed to load MCP servers",
          type: "error",
        });
      } finally {
        setLoading(false);
        setHasFetched(true);
      }
    };

    fetchMCPServers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAssistant?.id]);

  // Function to refresh server data
  const refreshServers = async () => {
    const assistantId = selectedAssistant?.id;
    if (!assistantId) return;

    try {
      setLoading(true);
      const response = await fetch(`/api/mcp/servers/${assistantId}`);
      if (!response.ok) {
        throw new Error("Failed to fetch MCP servers");
      }
      const data = await response.json();
      setMcpServers(data.mcp_servers || []);
    } catch (error) {
      console.error("Error refreshing MCP servers:", error);
    } finally {
      setLoading(false);
    }
  };

  const hasUnauthenticatedServers = mcpServers.some(
    (server) =>
      server.auth_performer === MCPAuthenticationPerformer.PER_USER &&
      server.auth_type !== MCPAuthenticationType.NONE &&
      !server.user_authenticated
  );

  const handleServerClick = (server: MCPServer) => {
    const authType = server.auth_type;
    const performer = server.auth_performer;

    // Only allow clicking for per-user auth servers that require auth
    if (
      authType === MCPAuthenticationType.NONE ||
      performer === MCPAuthenticationPerformer.ADMIN
    )
      return;

    // Handle authentication flows for per-user servers
    if (authType === MCPAuthenticationType.OAUTH) {
      // For OAuth, always redirect to re-authenticate
      onAuthenticateServer(server.id, MCPAuthenticationType.OAUTH);
    } else if (authType === MCPAuthenticationType.API_TOKEN) {
      // For API token, allow both initial auth and credential management
      onOpenApiKeyModal(
        server.id,
        server.name,
        server.auth_template,
        refreshServers,
        server.user_authenticated,
        server.user_credentials
      );
    }
  };

  const getServerIcon = (server: MCPServer) => {
    const authType = (server.auth_type || "").toLowerCase();
    const performer = (server.auth_performer || "").toLowerCase();
    if (authType === "none" || performer === "admin") {
      return <FiLock className="h-4 w-4 text-subtle" />;
    }

    if (server.user_authenticated) {
      return <FiCheck className="h-4 w-4 text-green-600" />;
    }

    if (authType === "oauth") {
      return <FiAlertTriangle className="h-4 w-4 text-amber-600" />;
    } else if (authType === "api_token") {
      return <FiKey className="h-4 w-4 text-amber-600" />;
    }

    return <FiServer className="h-4 w-4 text-subtle" />;
  };

  const getServerStatus = (server: MCPServer) => {
    const authType = (server.auth_type || "").toLowerCase();
    const performer = (server.auth_performer || "").toLowerCase();
    if (authType === "none") {
      return "No auth required";
    }

    if (performer === "admin") {
      return "Admin authenticated";
    }

    if (server.user_authenticated) {
      if (authType === "oauth") {
        return "Click to re-authenticate";
      } else if (authType === "api_token") {
        return "Click to manage API key";
      }
      return "Authenticated";
    }

    if (authType === "oauth") {
      return "Click to authenticate";
    } else if (authType === "api_token") {
      return "Enter API key";
    }

    return "Not authenticated";
  };

  const isServerClickable = (server: MCPServer) => {
    const authType = (server.auth_type || "").toLowerCase();
    const performer = (server.auth_performer || "").toLowerCase();
    // Clickable for per-user auth servers that require auth (both authenticated and unauthenticated)
    return performer === "per_user" && authType !== "none";
  };

  // Don't show the dropdown if there's no assistant selected
  if (!selectedAssistant?.id) {
    return null;
  }

  // Hide the dropdown if we've fetched and there are no servers
  if (hasFetched && mcpServers.length === 0) {
    return null;
  }

  return (
    <>
      {popup}
      <Popover open={isOpen} onOpenChange={setIsOpen}>
        <PopoverTrigger asChild>
          <button
            className={`
              relative 
              cursor-pointer 
              flex 
              items-center 
              space-x-1
              group
              rounded
              text-input-text
              hover:bg-background-chat-hover
              hover:text-neutral-900
              dark:hover:text-neutral-50
              py-1.5
              px-2
              flex-none 
              whitespace-nowrap 
              overflow-hidden
            `}
          >
            {loading ? (
              <FiLoader
                size={16}
                className="h-4 w-4 my-auto flex-none animate-spin"
              />
            ) : (
              <FiServer size={16} className="h-4 w-4 my-auto flex-none" />
            )}
            <div className="flex items-center">
              {/* <span className="text-sm break-all line-clamp-1">MCP</span> */}
              {hasUnauthenticatedServers && !loading && (
                <div className="ml-1 h-2 w-2 bg-amber-500 rounded-full" />
              )}
              {/* <FiChevronDown className="flex-none ml-1" size={12} /> */}
            </div>
          </button>
        </PopoverTrigger>
        <PopoverContent
          className="bg-background w-[380px] p-0 shadow-lg"
          align="start"
        >
          <div className="p-3 border-b border-border">
            <h3 className="font-medium text-sm">MCP Servers</h3>
            <p className="text-xs text-subtle mt-1">
              Manage authentication for MCP servers used by this assistant
            </p>
          </div>
          <div className="max-h-64 overflow-y-auto">
            {loading ? (
              <div className="flex items-center justify-center py-6">
                <FiLoader className="animate-spin h-5 w-5 text-subtle" />
                <span className="ml-2 text-sm text-subtle">
                  Loading MCP servers...
                </span>
              </div>
            ) : mcpServers.length === 0 ? (
              <div className="p-4 text-center text-subtle">
                No MCP servers configured for this assistant
              </div>
            ) : (
              mcpServers.map((server) => (
                <div
                  key={server.id}
                  className={`
                  p-3 border-b border-border last:border-b-0 
                  ${
                    isServerClickable(server)
                      ? "cursor-pointer hover:bg-background-50"
                      : "cursor-default"
                  }
                  ${(() => {
                    const authType = (server.auth_type || "").toLowerCase();
                    const performer = (
                      server.auth_performer || ""
                    ).toLowerCase();
                    return authType === "none" || performer === "admin"
                      ? "opacity-60"
                      : "";
                  })()}
                `}
                  onClick={() => handleServerClick(server)}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-3">
                      {getServerIcon(server)}
                      <div>
                        <div className="font-medium text-sm">{server.name}</div>
                        <div className="text-xs text-subtle">
                          {server.server_url}
                        </div>
                      </div>
                    </div>
                    <div className="flex-shrink-0">
                      <div
                        className={`
                        text-xs px-2 py-1 rounded-full whitespace-nowrap
                        ${
                          server.user_authenticated
                            ? "bg-green-100 text-green-800"
                            : server.auth_type === MCPAuthenticationType.NONE ||
                                server.auth_performer ===
                                  MCPAuthenticationPerformer.ADMIN
                              ? "bg-gray-100 text-gray-600"
                              : "bg-amber-100 text-amber-800"
                        }
                      `}
                      >
                        {getServerStatus(server)}
                      </div>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </PopoverContent>
      </Popover>
    </>
  );
}
