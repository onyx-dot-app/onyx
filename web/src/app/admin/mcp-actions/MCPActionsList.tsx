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
import { useState } from "react";
import MCPAuthenticationModal from "./MCPAuthenticationModal";
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
  const [selectedServer, setSelectedServer] =
    useState<MCPServerWithStatus | null>(null);

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
    console.log("Disconnect server:", serverId);
  };

  const handleManage = (serverId: number) => {
    console.log("Manage server:", serverId);
  };

  const handleEdit = (serverId: number) => {
    console.log("Edit server:", serverId);
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
    console.log("Reconnect server:", serverId);
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
        <MCPAuthenticationModal mcpServer={selectedServer} />
      </authModal.Provider>
    </div>
  );
}
