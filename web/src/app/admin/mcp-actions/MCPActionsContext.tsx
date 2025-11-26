"use client";

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
} from "react";
import useSWR, { KeyedMutator } from "swr";
import { MCPServersResponse, ToolSnapshot } from "@/lib/tools/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { usePopup, PopupSpec } from "@/components/admin/connectors/Popup";
import {
  useCreateModal,
  ModalCreationInterface,
} from "@/refresh-components/contexts/ModalContext";
import {
  deleteMCPServer,
  refreshMCPServerTools,
  updateToolStatus,
  disableAllServerTools,
  updateMCPServerStatus,
} from "@/lib/mcpService";
import { MCPServerWithStatus } from "./types";

interface MCPActionsContextValue {
  // Data
  mcpServers: MCPServerWithStatus[];
  mutateMcpServers: KeyedMutator<MCPServersResponse>;
  isLoading: boolean;
  fetchingToolsServerIds: number[];

  // Notifications
  popup: React.ReactElement | null;
  setPopup: (spec: PopupSpec) => void;

  // Modal states
  authModal: ModalCreationInterface;
  disconnectModal: ModalCreationInterface;
  manageServerModal: ModalCreationInterface;

  // Selected servers
  selectedServer: MCPServerWithStatus | null;
  serverToDisconnect: MCPServerWithStatus | null;
  serverToManage: MCPServerWithStatus | null;
  setServerToDisconnect: React.Dispatch<
    React.SetStateAction<MCPServerWithStatus | null>
  >;
  setServerToManage: React.Dispatch<
    React.SetStateAction<MCPServerWithStatus | null>
  >;

  // Operations
  handleAuthenticate: (serverId: number) => void;
  handleDisconnect: (serverId: number) => void;
  handleDelete: (serverId: number) => Promise<void>;
  handleReconnect: (serverId: number) => Promise<void>;
  handleManage: (serverId: number) => void;
  handleEdit: (serverId: number) => void;
  handleConfirmDisconnect: () => Promise<void>;
  handleConfirmDisconnectAndDelete: () => Promise<void>;

  // Tool operations
  handleToolToggle: (
    serverId: number,
    toolId: string,
    enabled: boolean,
    mutateServerTools: KeyedMutator<ToolSnapshot[]>
  ) => Promise<void>;
  handleRefreshTools: (
    serverId: number,
    mutateServerTools: KeyedMutator<ToolSnapshot[]>
  ) => Promise<void>;
  handleDisableAllTools: (
    serverId: number,
    toolIds: number[],
    mutateServerTools: KeyedMutator<ToolSnapshot[]>
  ) => Promise<void>;

  // Other state
  showSharedOverlay: boolean;
  isDisconnecting: boolean;
  onServerCreated: (server: MCPServerWithStatus) => void;
}

const MCPActionsContext = createContext<MCPActionsContextValue | undefined>(
  undefined
);

export function MCPActionsProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const { popup, setPopup } = usePopup();
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
  const [fetchingToolsServerIds, setFetchingToolsServerIds] = useState<
    number[]
  >([]);

  // Fetch MCP servers
  const {
    data: mcpData,
    isLoading: isMcpLoading,
    mutate: mutateMcpServers,
  } = useSWR<MCPServersResponse>(
    "/api/admin/mcp/servers",
    errorHandlingFetcher
  );

  const mcpServers = useMemo(
    () => (mcpData?.mcp_servers || []) as MCPServerWithStatus[],
    [mcpData?.mcp_servers]
  );
  const isLoading = isMcpLoading;

  useEffect(() => {
    if (mcpServers) {
      const fetchingIds = mcpServers
        .filter((server) => server.status === "FETCHING_TOOLS")
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

  const handleDisconnect = useCallback(
    (serverId: number) => {
      const server = mcpServers.find((s) => s.id === serverId);
      if (server) {
        setServerToDisconnect(server);
        disconnectModal.toggle(true);
      }
    },
    [mcpServers, disconnectModal]
  );

  const handleConfirmDisconnect = useCallback(async () => {
    if (!serverToDisconnect) return;

    setIsDisconnecting(true);
    try {
      await updateMCPServerStatus(serverToDisconnect.id, "DISCONNECTED");

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
  }, [serverToDisconnect, setPopup, mutateMcpServers, disconnectModal]);

  const handleConfirmDisconnectAndDelete = useCallback(async () => {
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
  }, [serverToDisconnect, setPopup, mutateMcpServers, disconnectModal]);

  const handleManage = useCallback(
    (serverId: number) => {
      const server = mcpServers.find((s) => s.id === serverId);
      if (server) {
        setServerToManage(server);
        manageServerModal.toggle(true);
      }
    },
    [mcpServers, manageServerModal]
  );

  const handleEdit = useCallback(
    (serverId: number) => {
      const server = mcpServers.find((s) => s.id === serverId);
      if (server) {
        setServerToManage(server);
        manageServerModal.toggle(true);
      }
    },
    [mcpServers, manageServerModal]
  );

  const handleDelete = useCallback(
    async (serverId: number) => {
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
    },
    [setPopup, mutateMcpServers]
  );

  const handleAuthenticate = useCallback(
    (serverId: number) => {
      const server = mcpServers.find((s) => s.id === serverId);
      if (server) {
        setSelectedServer(server);
        authModal.toggle(true);
      }
    },
    [mcpServers, authModal]
  );

  const handleReconnect = useCallback(
    async (serverId: number) => {
      try {
        await updateMCPServerStatus(serverId, "CONNECTED");

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
    },
    [setPopup, mutateMcpServers]
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
    },
    [setPopup]
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
    },
    [mutateMcpServers, setPopup]
  );

  const handleDisableAllTools = useCallback(
    async (
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
    },
    [setPopup]
  );

  const onServerCreated = useCallback(
    (server: MCPServerWithStatus) => {
      console.log("Server created:", server);
      setSelectedServer(server);
      authModal.toggle(true);
    },
    [authModal]
  );

  const value: MCPActionsContextValue = useMemo(
    () => ({
      // Data
      mcpServers,
      mutateMcpServers,
      isLoading,
      fetchingToolsServerIds,
      // Notifications
      popup,
      setPopup,

      // Modal states
      authModal,
      disconnectModal,
      manageServerModal,

      // Selected servers
      selectedServer,
      serverToDisconnect,
      serverToManage,
      setServerToDisconnect,
      setServerToManage,

      // Operations
      handleAuthenticate,
      handleDisconnect,
      handleDelete,
      handleReconnect,
      handleManage,
      handleEdit,
      handleConfirmDisconnect,
      handleConfirmDisconnectAndDelete,

      // Tool operations
      handleToolToggle,
      handleRefreshTools,
      handleDisableAllTools,

      // Other state
      showSharedOverlay,
      isDisconnecting,
      onServerCreated,
    }),
    [
      mcpServers,
      mutateMcpServers,
      isLoading,
      fetchingToolsServerIds,
      popup,
      setPopup,
      authModal,
      disconnectModal,
      manageServerModal,
      selectedServer,
      serverToDisconnect,
      serverToManage,
      showSharedOverlay,
      isDisconnecting,
      handleAuthenticate,
      handleDisconnect,
      handleDelete,
      handleReconnect,
      handleManage,
      handleEdit,
      handleConfirmDisconnect,
      handleConfirmDisconnectAndDelete,
      handleToolToggle,
      handleRefreshTools,
      handleDisableAllTools,
      onServerCreated,
    ]
  );

  return (
    <MCPActionsContext.Provider value={value}>
      {children}
    </MCPActionsContext.Provider>
  );
}

export function useMCPActions() {
  const context = useContext(MCPActionsContext);
  if (context === undefined) {
    throw new Error("useMCPActions must be used within a MCPActionsProvider");
  }
  return context;
}
