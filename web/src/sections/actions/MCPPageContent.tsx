"use client";

import { useState, useCallback, useMemo, useEffect } from "react";
import { KeyedMutator } from "swr";
import MCPActionCard from "@/sections/actions/MCPActionCard";
import Actionbar from "@/sections/actions/Actionbar";
import ActionCardSkeleton from "@/sections/actions/skeleton/ActionCardSkeleton";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import {
  ActionStatus,
  MCPServerStatus,
  MCPServer,
  ToolSnapshot,
} from "@/lib/tools/interfaces";
import { toast } from "@/hooks/useToast";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import MCPAuthenticationModal from "@/sections/actions/modals/MCPAuthenticationModal";
import AddMCPServerModal from "@/sections/actions/modals/AddMCPServerModal";
import DisconnectEntityModal from "./modals/DisconnectEntityModal";
import {
  deleteMCPServer,
  refreshMCPServerTools,
  updateToolStatus,
  updateMCPServerStatus,
  updateMCPServer,
  updateToolsStatus,
} from "@/lib/tools/mcpService";
import { useSearchParams } from "next/navigation";
import { useRouter } from "next/navigation";
import useMcpServers from "@/hooks/useMcpServers";

export default function MCPPageContent() {
  // Data fetching
  const {
    mcpData,
    isLoading: isMcpLoading,
    mutateMcpServers,
  } = useMcpServers();

  // Modal management
  const authModal = useCreateModal();
  const disconnectModal = useCreateModal();
  const manageServerModal = useCreateModal();

  // Local state
  const [activeServer, setActiveServer] = useState<MCPServer | null>(null);
  const [serverToExpand, setServerToExpand] = useState<number | null>(null);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [showSharedOverlay, setShowSharedOverlay] = useState(false);
  const [fetchingToolsServerIds, setFetchingToolsServerIds] = useState<
    number[]
  >([]);
  const [searchQuery, setSearchQuery] = useState("");

  const mcpServers = useMemo(
    () => (mcpData?.mcp_servers || []) as MCPServer[],
    [mcpData?.mcp_servers]
  );
  const isLoading = isMcpLoading;

  const searchParams = useSearchParams();
  const router = useRouter();

  useEffect(() => {
    const serverId = searchParams.get("server_id");
    const triggerFetch = searchParams.get("trigger_fetch");

    // Only process if we have a server_id and trigger_fetch flag
    if (
      serverId &&
      triggerFetch === "true" &&
      !fetchingToolsServerIds.includes(parseInt(serverId))
    ) {
      const serverIdInt = parseInt(serverId);

      const handleFetchingTools = async () => {
        try {
          await updateMCPServerStatus(
            serverIdInt,
            MCPServerStatus.FETCHING_TOOLS
          );

          await mutateMcpServers();

          router.replace("/admin/actions/mcp");

          // Automatically expand the tools for this server
          setServerToExpand(serverIdInt);

          await refreshMCPServerTools(serverIdInt);

          toast.success("Successfully connected and fetched tools");

          await mutateMcpServers();
        } catch (error) {
          console.error("Failed to fetch tools:", error);
          toast.error(
            `Failed to fetch tools: ${
              error instanceof Error ? error.message : "Unknown error"
            }`
          );
          await mutateMcpServers();
        }
      };

      handleFetchingTools();
    }
  }, [
    searchParams,
    router,
    fetchingToolsServerIds,
    mutateMcpServers,
    setServerToExpand,
  ]);

  // Track fetching tools server IDs
  useEffect(() => {
    if (mcpServers) {
      const fetchingIds = mcpServers
        .filter((server) => server.status === MCPServerStatus.FETCHING_TOOLS)
        .map((server) => server.id);
      setFetchingToolsServerIds(fetchingIds);
    }
  }, [mcpServers]);

  // Track if any modal is open to manage the shared overlay
  useEffect(() => {
    const anyModalOpen =
      authModal.isOpen || disconnectModal.isOpen || manageServerModal.isOpen;
    setShowSharedOverlay(anyModalOpen);
  }, [authModal.isOpen, disconnectModal.isOpen, manageServerModal.isOpen]);

  // Determine action status based on server status field
  const getActionStatusForServer = useCallback(
    (server: MCPServer): ActionStatus => {
      if (server.status === MCPServerStatus.CONNECTED) {
        return ActionStatus.CONNECTED;
      } else if (
        server.status === MCPServerStatus.AWAITING_AUTH ||
        server.status === MCPServerStatus.CREATED
      ) {
        return ActionStatus.PENDING;
      } else if (server.status === MCPServerStatus.FETCHING_TOOLS) {
        return ActionStatus.FETCHING;
      }
      return ActionStatus.DISCONNECTED;
    },
    []
  );

  // Handler callbacks
  const handleDisconnect = useCallback(
    (serverId: number) => {
      const server = mcpServers.find((s) => s.id === serverId);
      if (server) {
        setActiveServer(server);
        disconnectModal.toggle(true);
      }
    },
    [mcpServers, disconnectModal]
  );

  const handleConfirmDisconnect = useCallback(async () => {
    if (!activeServer) return;

    setIsDisconnecting(true);
    try {
      await updateMCPServerStatus(
        activeServer.id,
        MCPServerStatus.DISCONNECTED
      );

      toast.success("MCP Server disconnected successfully");

      await mutateMcpServers();
      disconnectModal.toggle(false);
      setActiveServer(null);
    } catch (error) {
      console.error("Error disconnecting server:", error);
      toast.error(
        error instanceof Error
          ? error.message
          : "Failed to disconnect MCP Server"
      );
    } finally {
      setIsDisconnecting(false);
    }
  }, [activeServer, mutateMcpServers, disconnectModal]);

  const handleConfirmDisconnectAndDelete = useCallback(async () => {
    if (!activeServer) return;

    setIsDisconnecting(true);
    try {
      await deleteMCPServer(activeServer.id);

      toast.success("MCP Server deleted successfully");

      await mutateMcpServers();
      disconnectModal.toggle(false);
      setActiveServer(null);
    } catch (error) {
      console.error("Error deleting server:", error);
      toast.error(
        error instanceof Error ? error.message : "Failed to delete MCP Server"
      );
    } finally {
      setIsDisconnecting(false);
    }
  }, [activeServer, mutateMcpServers, disconnectModal]);

  const openManageServerModal = useCallback(
    (serverId: number) => {
      const server = mcpServers.find((s) => s.id === serverId);
      if (server) {
        setActiveServer(server);
        manageServerModal.toggle(true);
      }
    },
    [mcpServers, manageServerModal]
  );

  const handleManage = useCallback(
    (serverId: number) => {
      openManageServerModal(serverId);
    },
    [openManageServerModal]
  );

  const handleEdit = useCallback(
    (serverId: number) => {
      openManageServerModal(serverId);
    },
    [openManageServerModal]
  );

  const handleDelete = useCallback(
    async (serverId: number) => {
      try {
        await deleteMCPServer(serverId);

        toast.success("MCP Server deleted successfully");

        await mutateMcpServers();
      } catch (error) {
        console.error("Error deleting server:", error);
        toast.error(
          error instanceof Error ? error.message : "Failed to delete MCP Server"
        );
      }
    },
    [mutateMcpServers]
  );

  const handleAuthenticate = useCallback(
    (serverId: number) => {
      const server = mcpServers.find((s) => s.id === serverId);
      if (server) {
        setActiveServer(server);
        authModal.toggle(true);
      }
    },
    [mcpServers, authModal]
  );

  const triggerFetchToolsInPlace = useCallback(
    async (serverId: number) => {
      if (fetchingToolsServerIds.includes(serverId)) {
        return;
      }

      try {
        // Expand tools list immediately so the user sees the skeleton
        setServerToExpand(serverId);

        await updateMCPServerStatus(serverId, MCPServerStatus.FETCHING_TOOLS);
        await mutateMcpServers();

        await refreshMCPServerTools(serverId);

        toast.success("Successfully connected and fetched tools");

        await mutateMcpServers();
      } catch (error) {
        console.error("Failed to fetch tools:", error);
        toast.error(
          `Failed to fetch tools: ${
            error instanceof Error ? error.message : "Unknown error"
          }`
        );
        await mutateMcpServers();
      }
    },
    [fetchingToolsServerIds, mutateMcpServers, setServerToExpand]
  );

  const handleReconnect = useCallback(
    async (serverId: number) => {
      try {
        await updateMCPServerStatus(serverId, MCPServerStatus.CONNECTED);

        toast.success("MCP Server reconnected successfully");

        await mutateMcpServers();
      } catch (error) {
        console.error("Error reconnecting server:", error);
        toast.error(
          error instanceof Error
            ? error.message
            : "Failed to reconnect MCP Server"
        );
      }
    },
    [mutateMcpServers]
  );

  const handleToolToggle = useCallback(
    async (
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

        toast.success(`Tool ${enabled ? "enabled" : "disabled"} successfully`);
      } catch (error) {
        console.error("Error toggling tool:", error);

        // Revert on error by revalidating
        await mutateServerTools();

        toast.error(
          error instanceof Error ? error.message : "Failed to update tool"
        );
      }
    },
    []
  );

  const handleRefreshTools = useCallback(
    async (
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

        toast.success("Tools refreshed successfully");
      } catch (error) {
        console.error("Error refreshing tools:", error);
        toast.error(
          error instanceof Error ? error.message : "Failed to refresh tools"
        );
      }
    },
    [mutateMcpServers]
  );

  const handleUpdateToolsStatus = useCallback(
    async (
      serverId: number,
      toolIds: number[],
      enabled: boolean,
      mutateServerTools: KeyedMutator<ToolSnapshot[]>
    ) => {
      try {
        if (toolIds.length === 0) {
          toast.info("No tools to disable");
          return;
        }

        // Optimistically update - disable all tools in the UI
        await mutateServerTools(
          async (currentTools) => {
            if (!currentTools) return currentTools;
            return currentTools.map((tool) =>
              toolIds.includes(tool.id) ? { ...tool, enabled } : tool
            );
          },
          { revalidate: false }
        );

        const result = await updateToolsStatus(toolIds, enabled);

        // Revalidate to get fresh data from server
        await mutateServerTools();

        toast.success(
          `${result.updated_count} tool${
            result.updated_count !== 1 ? "s" : ""
          } ${enabled ? "enabled" : "disabled"} successfully`
        );
      } catch (error) {
        console.error(
          `Error ${enabled ? "enabling" : "disabling"} all tools:`,
          error
        );

        // Revert on error by revalidating
        await mutateServerTools();

        toast.error(
          error instanceof Error
            ? error.message
            : `Failed to ${enabled ? "enable" : "disable"} all tools`
        );
      }
    },
    []
  );

  const onServerCreated = useCallback(
    (server: MCPServer) => {
      setActiveServer(server);
      authModal.toggle(true);
    },
    [authModal]
  );

  const handleAddServer = useCallback(() => {
    setActiveServer(null);
    manageServerModal.toggle(true);
  }, [manageServerModal]);

  const handleRenameServer = useCallback(
    async (serverId: number, newName: string) => {
      try {
        await updateMCPServer(serverId, { name: newName });
        toast.success("MCP Server renamed successfully");
        await mutateMcpServers();
      } catch (error) {
        console.error("Error renaming server:", error);
        toast.error(
          error instanceof Error ? error.message : "Failed to rename MCP Server"
        );
        throw error; // Re-throw so ButtonRenaming can handle it
      }
    },
    [mutateMcpServers]
  );

  // Filter servers based on search query
  const filteredServers = useMemo(() => {
    if (!searchQuery.trim()) return mcpServers;

    const query = searchQuery.toLowerCase();
    return mcpServers.filter(
      (server) =>
        server.name.toLowerCase().includes(query) ||
        server.description?.toLowerCase().includes(query) ||
        server.server_url.toLowerCase().includes(query)
    );
  }, [mcpServers, searchQuery]);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Shared overlay that persists across modal transitions */}
      {showSharedOverlay && (
        <div
          className="fixed inset-0 z-modal-overlay bg-mask-03 backdrop-blur-03 pointer-events-none data-[state=open]:animate-in data-[state=open]:fade-in-0"
          data-state="open"
          aria-hidden="true"
        />
      )}

      <div className="flex-shrink-0 mb-4">
        <Actionbar
          hasActions={isLoading || mcpServers.length > 0}
          searchQuery={searchQuery}
          onSearchQueryChange={setSearchQuery}
          onAddAction={handleAddServer}
          buttonText="Add MCP Server"
          barText="Connect MCP server to add custom actions."
        />
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        <div className="flex flex-col gap-4 w-full pb-4">
          {isLoading ? (
            <>
              <ActionCardSkeleton />
              <ActionCardSkeleton />
            </>
          ) : (
            filteredServers.map((server) => {
              const status = getActionStatusForServer(server);

              return (
                <MCPActionCard
                  key={server.id}
                  serverId={server.id}
                  server={server}
                  title={server.name}
                  description={server.description || server.server_url}
                  logo={getActionIcon(server.server_url, server.name)}
                  status={status}
                  toolCount={server.tool_count}
                  initialExpanded={server.id === serverToExpand}
                  onDisconnect={() => handleDisconnect(server.id)}
                  onManage={() => handleManage(server.id)}
                  onEdit={() => handleEdit(server.id)}
                  onDelete={() => handleDelete(server.id)}
                  onAuthenticate={() => handleAuthenticate(server.id)}
                  onReconnect={() => handleReconnect(server.id)}
                  onRename={handleRenameServer}
                  onToolToggle={handleToolToggle}
                  onRefreshTools={handleRefreshTools}
                  onUpdateToolsStatus={handleUpdateToolsStatus}
                />
              );
            })
          )}
        </div>
      </div>

      <authModal.Provider>
        <MCPAuthenticationModal
          mcpServer={activeServer}
          skipOverlay
          onTriggerFetchTools={triggerFetchToolsInPlace}
          mutateMcpServers={mutateMcpServers}
        />
      </authModal.Provider>

      <manageServerModal.Provider>
        <AddMCPServerModal
          skipOverlay
          activeServer={activeServer}
          setActiveServer={setActiveServer}
          disconnectModal={disconnectModal}
          manageServerModal={manageServerModal}
          onServerCreated={onServerCreated}
          handleAuthenticate={handleAuthenticate}
          mutateMcpServers={async () => {
            await mutateMcpServers();
          }}
        />
      </manageServerModal.Provider>

      <DisconnectEntityModal
        isOpen={disconnectModal.isOpen}
        onClose={() => {
          disconnectModal.toggle(false);
          setActiveServer(null);
        }}
        name={activeServer?.name ?? null}
        onConfirmDisconnect={handleConfirmDisconnect}
        onConfirmDisconnectAndDelete={handleConfirmDisconnectAndDelete}
        isDisconnecting={isDisconnecting}
        skipOverlay
      />
    </div>
  );
}
