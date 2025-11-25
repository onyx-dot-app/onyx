"use client";
import ActionCard from "@/sections/actions/ActionCard";
import { getMCPServerIcon } from "@/lib/mcpUtils";
import {
  deleteMCPServer,
  refreshMCPServerTools,
  updateToolStatus,
  disableAllServerTools,
} from "@/lib/mcpService";
import {
  MCPActionsListProps,
  MCPActionStatus,
  MCPServerWithStatus,
} from "./types";
import { useState, useEffect } from "react";
import MCPAuthenticationModal from "./MCPAuthenticationModal";
import DisconnectMCPModal from "./DisconnectMCPModal";
import AddMCPServerModal from "./AddMCPServerModal";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { KeyedMutator } from "swr";

export default function MCPActionsList({
  mcpServers,
  mutateMcpServers,
  setPopup,
  toolsFetchingServerIds,
}: MCPActionsListProps) {
  const authModal = useCreateModal();
  const disconnectModal = useCreateModal();
  const manageServerModal = useCreateModal();
  const [selectedServer, setSelectedServer] =
    useState<MCPServerWithStatus | null>(null);
  const [serverToDisconnect, setServerToDisconnect] =
    useState<MCPServerWithStatus | null>(null);
  const [serverToManage, setServerToManage] =
    useState<MCPServerWithStatus | null>(null);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [showSharedOverlay, setShowSharedOverlay] = useState(false);

  // Track if any modal is open to manage the shared overlay
  useEffect(() => {
    const anyModalOpen =
      authModal.isOpen || disconnectModal.isOpen || manageServerModal.isOpen;
    setShowSharedOverlay(anyModalOpen);
  }, [authModal.isOpen, disconnectModal.isOpen, manageServerModal.isOpen]);

  // Determine status based on server status field
  const getStatus = (server: MCPServerWithStatus): MCPActionStatus => {
    if (server.status === "CONNECTED") {
      return "connected";
    } else if (
      server.status === "AWAITING_AUTH" ||
      server.status === "CREATED"
    ) {
      return "pending";
    }
    return "disconnected";
  };

  const handleDisconnect = async (serverId: number) => {
    const server = mcpServers.find((s) => s.id === serverId);
    if (server) {
      setServerToDisconnect(server);
      disconnectModal.toggle(true);
    }
  };

  const handleConfirmDisconnect = async () => {
    if (!serverToDisconnect) return;

    setIsDisconnecting(true);
    try {
      const response = await fetch(
        `/api/admin/mcp/server/${serverToDisconnect.id}/status?status=DISCONNECTED`,
        {
          method: "PATCH",
        }
      );

      if (!response.ok) {
        throw new Error("Failed to disconnect MCP server");
      }

      setPopup({
        message: "MCP Server disconnected successfully",
        type: "success",
      });

      await mutateMcpServers();
      disconnectModal.toggle(false);
      setServerToDisconnect(null);
    } catch (error) {
      console.error("Error disconnecting server:", error);
      setPopup({
        message:
          error instanceof Error
            ? error.message
            : "Failed to disconnect MCP Server",
        type: "error",
      });
    } finally {
      setIsDisconnecting(false);
    }
  };

  const handleConfirmDisconnectAndDelete = async () => {
    if (!serverToDisconnect) return;

    setIsDisconnecting(true);
    try {
      await deleteMCPServer(serverToDisconnect.id);

      setPopup({
        message: "MCP Server deleted successfully",
        type: "success",
      });

      await mutateMcpServers();
      disconnectModal.toggle(false);
      setServerToDisconnect(null);
    } catch (error) {
      console.error("Error deleting server:", error);
      setPopup({
        message:
          error instanceof Error
            ? error.message
            : "Failed to delete MCP Server",
        type: "error",
      });
    } finally {
      setIsDisconnecting(false);
    }
  };

  const handleManage = (serverId: number) => {
    const server = mcpServers.find((s) => s.id === serverId);
    if (server) {
      setServerToManage(server);
      manageServerModal.toggle(true);
    }
  };

  const handleEdit = (serverId: number) => {
    const server = mcpServers.find((s) => s.id === serverId);
    if (server) {
      setServerToManage(server);
      manageServerModal.toggle(true);
    }
  };

  const handleDelete = async (serverId: number) => {
    try {
      await deleteMCPServer(serverId);

      setPopup({
        message: "MCP Server deleted successfully",
        type: "success",
      });

      await mutateMcpServers();
    } catch (error) {
      console.error("Error deleting server:", error);
      setPopup({
        message:
          error instanceof Error
            ? error.message
            : "Failed to delete MCP Server",
        type: "error",
      });
    }
  };

  const handleAuthenticate = async (serverId: number) => {
    const server = mcpServers.find((s) => s.id === serverId);
    if (server) {
      setSelectedServer(server);
      authModal.toggle(true);
    }
  };

  const handleReconnect = async (serverId: number) => {
    try {
      const response = await fetch(
        `/api/admin/mcp/server/${serverId}/status?status=CONNECTED`,
        {
          method: "PATCH",
        }
      );

      if (!response.ok) {
        throw new Error("Failed to reconnect MCP server");
      }

      setPopup({
        message: "MCP Server reconnected successfully",
        type: "success",
      });

      await mutateMcpServers();
    } catch (error) {
      console.error("Error reconnecting server:", error);
      setPopup({
        message:
          error instanceof Error
            ? error.message
            : "Failed to reconnect MCP Server",
        type: "error",
      });
    }
  };

  const handleToolToggle = async (
    serverId: number,
    toolId: string,
    enabled: boolean,
    mutateServerTools: KeyedMutator<ToolSnapshot[]>
  ) => {
    try {
      // Optimistically update the UI
      await mutateServerTools(
        async (currentTools) => {
          if (!currentTools) return currentTools;
          return currentTools.map((tool) =>
            tool.id.toString() === toolId ? { ...tool, enabled } : tool
          );
        },
        { revalidate: false }
      );

      await updateToolStatus(parseInt(toolId), enabled);

      // Revalidate to get fresh data from server
      await mutateServerTools();

      setPopup({
        message: `Tool ${enabled ? "enabled" : "disabled"} successfully`,
        type: "success",
      });
    } catch (error) {
      console.error("Error toggling tool:", error);

      // Revert on error by revalidating
      await mutateServerTools();

      setPopup({
        message:
          error instanceof Error ? error.message : "Failed to update tool",
        type: "error",
      });
    }
  };

  const handleRefreshTools = async (
    serverId: number,
    mutateServerTools: KeyedMutator<ToolSnapshot[]>
  ) => {
    try {
      // Refresh tools for this specific server (discovers from MCP and syncs to DB)
      await refreshMCPServerTools(serverId);

      // Update the local cache with fresh data
      await mutateServerTools();

      // Also refresh the servers list to update tool counts
      await mutateMcpServers();

      setPopup({
        message: "Tools refreshed successfully",
        type: "success",
      });
    } catch (error) {
      console.error("Error refreshing tools:", error);
      setPopup({
        message:
          error instanceof Error ? error.message : "Failed to refresh tools",
        type: "error",
      });
    }
  };

  const handleDisableAllTools = async (
    serverId: number,
    toolIds: number[],
    mutateServerTools: KeyedMutator<ToolSnapshot[]>
  ) => {
    try {
      if (toolIds.length === 0) {
        setPopup({
          message: "No tools to disable",
          type: "info",
        });
        return;
      }

      // Optimistically update - disable all tools in the UI
      await mutateServerTools(
        async (currentTools) => {
          if (!currentTools) return currentTools;
          return currentTools.map((tool) =>
            toolIds.includes(tool.id) ? { ...tool, enabled: false } : tool
          );
        },
        { revalidate: false }
      );

      const result = await disableAllServerTools(toolIds);

      // Revalidate to get fresh data from server
      await mutateServerTools();

      setPopup({
        message: `${result.updated_count} tool${
          result.updated_count !== 1 ? "s" : ""
        } disabled successfully`,
        type: "success",
      });
    } catch (error) {
      console.error("Error disabling all tools:", error);

      // Revert on error by revalidating
      await mutateServerTools();

      setPopup({
        message:
          error instanceof Error
            ? error.message
            : "Failed to disable all tools",
        type: "error",
      });
    }
  };

  return (
    <>
      {/* Shared overlay that persists across modal transitions */}
      {showSharedOverlay && (
        <div
          className="fixed inset-0 z-[2000] bg-mask-03 backdrop-blur-03 pointer-events-none data-[state=open]:animate-in data-[state=open]:fade-in-0"
          data-state="open"
          aria-hidden="true"
        />
      )}

      <div className="flex flex-col gap-4 w-full">
        {mcpServers.map((server) => {
          const status = getStatus(server);

          return (
            <ActionCard
              key={server.id}
              serverId={server.id}
              server={server}
              title={server.name}
              description={server.description || server.server_url}
              logo={getMCPServerIcon(server)}
              status={status}
              toolCount={server.tool_count}
              onDisconnect={() => handleDisconnect(server.id)}
              onManage={() => handleManage(server.id)}
              onEdit={() => handleEdit(server.id)}
              onDelete={() => handleDelete(server.id)}
              onAuthenticate={() => handleAuthenticate(server.id)}
              onReconnect={() => handleReconnect(server.id)}
              onToolToggle={handleToolToggle}
              onRefreshTools={handleRefreshTools}
              onDisableAllTools={handleDisableAllTools}
              isInitialToolsFetching={toolsFetchingServerIds.includes(
                server.id.toString()
              )}
            />
          );
        })}

        <authModal.Provider>
          <MCPAuthenticationModal mcpServer={selectedServer} skipOverlay />
        </authModal.Provider>

        <DisconnectMCPModal
          isOpen={disconnectModal.isOpen}
          onClose={() => {
            disconnectModal.toggle(false);
            setServerToDisconnect(null);
          }}
          server={serverToDisconnect}
          onConfirmDisconnect={handleConfirmDisconnect}
          onConfirmDisconnectAndDelete={handleConfirmDisconnectAndDelete}
          isDisconnecting={isDisconnecting}
          skipOverlay
        />

        <manageServerModal.Provider>
          <AddMCPServerModal
            server={serverToManage || undefined}
            mutateMcpServers={mutateMcpServers}
            setPopup={setPopup}
            skipOverlay
            onDisconnect={() => {
              if (serverToManage) {
                // Set the server to disconnect first
                setServerToDisconnect(serverToManage);
                // Close manage modal and open disconnect modal simultaneously
                // The shared overlay persists, so no flash
                manageServerModal.toggle(false);
                disconnectModal.toggle(true);
              }
            }}
          />
        </manageServerModal.Provider>
      </div>
    </>
  );
}
