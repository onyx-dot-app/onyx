"use client";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import ActionCard from "@/sections/actions/ActionCard";
import { Tool } from "@/sections/actions/ToolsList";
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

export default function MCPActionsList({
  mcpServers,
  toolsByServer,
  mutateMcpServers,
  mutateTools,
  setPopup,
}: MCPActionsListProps) {
  const convertTools = (
    toolSnapshots: ToolSnapshot[],
    server: MCPServerWithStatus
  ): Tool[] => {
    return toolSnapshots.map((tool) => ({
      id: tool.id.toString(),
      icon: getMCPServerIcon(server),
      name: tool.display_name || tool.name,
      description: tool.description,
      isAvailable: true,
      isEnabled: tool.enabled,
    }));
  };

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

      await Promise.all([mutateMcpServers(), mutateTools()]);
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
    console.log("Authenticate server:", serverId);
  };

  const handleReconnect = async (serverId: number) => {
    console.log("Reconnect server:", serverId);
  };

  const handleToolToggle = async (
    serverId: number,
    toolId: string,
    enabled: boolean
  ) => {
    try {
      await mutateTools(async (currentTools) => {
        if (!currentTools) return currentTools;

        return currentTools.map((tool) =>
          tool.id.toString() === toolId ? { ...tool, enabled: enabled } : tool
        );
      }, false);

      await updateToolStatus(parseInt(toolId), enabled);

      await mutateTools();

      setPopup({
        message: `Tool ${enabled ? "enabled" : "disabled"} successfully`,
        type: "success",
      });
    } catch (error) {
      console.error("Error toggling tool:", error);

      await mutateTools();

      setPopup({
        message:
          error instanceof Error ? error.message : "Failed to update tool",
        type: "error",
      });
    }
  };

  const handleRefreshTools = async (serverId: number) => {
    try {
      await refreshMCPServerTools(serverId);

      setPopup({
        message: "Tools refreshed successfully",
        type: "success",
      });

      await mutateTools();
    } catch (error) {
      console.error("Error refreshing tools:", error);
      setPopup({
        message:
          error instanceof Error ? error.message : "Failed to refresh tools",
        type: "error",
      });
    }
  };

  const handleDisableAllTools = async (serverId: number) => {
    try {
      const serverTools = toolsByServer[serverId] || [];

      if (serverTools.length === 0) {
        setPopup({
          message: "No tools to disable",
          type: "info",
        });
        return;
      }

      const toolIds = serverTools.map((tool) => tool.id);

      await mutateTools(
        async (currentTools) => {
          if (!currentTools) return currentTools;

          return currentTools.map((tool) =>
            tool.mcp_server_id === serverId ? { ...tool, enabled: false } : tool
          );
        },
        false // Don't revalidate yet
      );

      const result = await disableAllServerTools(toolIds);

      setPopup({
        message: `${result.updated_count} tool${
          result.updated_count !== 1 ? "s" : ""
        } disabled successfully`,
        type: "success",
      });

      await mutateTools();
    } catch (error) {
      console.error("Error disabling all tools:", error);

      await mutateTools();

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
        const serverTools = toolsByServer[server.id] || [];
        const tools = convertTools(serverTools, server);
        const status = getStatus(server);

        return (
          <ActionCard
            key={server.id}
            title={server.name}
            description={server.description || server.server_url}
            logo={getMCPServerIcon(server)}
            status={status}
            toolCount={tools.length}
            tools={tools}
            onDisconnect={() => handleDisconnect(server.id)}
            onManage={() => handleManage(server.id)}
            onEdit={() => handleEdit(server.id)}
            onDelete={() => handleDelete(server.id)}
            onAuthenticate={() => handleAuthenticate(server.id)}
            onReconnect={() => handleReconnect(server.id)}
            onToolToggle={(toolId, enabled) =>
              handleToolToggle(server.id, toolId, enabled)
            }
            onRefreshTools={() => handleRefreshTools(server.id)}
            onDisableAllTools={() => handleDisableAllTools(server.id)}
          />
        );
      })}
    </div>
  );
}
