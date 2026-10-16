"use client";

import {
  useState,
  useCallback,
  useEffect,
  useRef,
  type ReactNode,
} from "react";
import { useTranslations } from "next-intl";
import { MCPServerStatus, type MCPServer } from "@/lib/mcp/types";
import { toast } from "@opal/layouts";
import { useCreateModal } from "@opal/components";
import MCPAuthenticationModal from "@/sections/actions/modals/MCPAuthenticationModal";
import AddMCPServerModal from "@/sections/actions/modals/AddMCPServerModal";
import DisconnectEntityModal from "@/sections/actions/modals/DisconnectEntityModal";
import {
  deleteMCPServer,
  refreshMCPServerTools,
  updateMCPServerStatus,
} from "@/lib/mcp/svc";

interface McpServerDialogActions {
  add: () => void;
  manage: (serverId: number) => void;
  authenticate: (serverId: number) => void;
  disconnect: (serverId: number) => void;
  delete: (serverId: number) => Promise<void>;
}

interface McpServerDialogsProps {
  servers: MCPServer[];
  initialServer?: MCPServer;
  onChanged: () => Promise<void>;
  onClosed?: () => void;
  onToolsFetching?: (serverId: number) => void;
  children?: (actions: McpServerDialogActions) => ReactNode;
}

/** Shared source-management workflow for Actions and Craft Apps. */
export default function McpServerDialogs({
  servers: mcpServers,
  initialServer,
  onChanged,
  onClosed,
  onToolsFetching,
  children,
}: McpServerDialogsProps) {
  const t = useTranslations("actions");
  const authModal = useCreateModal();
  const disconnectModal = useCreateModal();
  const manageServerModal = useCreateModal();
  const [activeServer, setActiveServer] = useState<MCPServer | null>(null);
  const currentActiveServer =
    mcpServers.find((server) => server.id === activeServer?.id) ?? activeServer;
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const fetchingToolsServerIds = mcpServers
    .filter((server) => server.status === MCPServerStatus.FETCHING_TOOLS)
    .map((server) => server.id);
  const showSharedOverlay =
    authModal.isOpen || disconnectModal.isOpen || manageServerModal.isOpen;
  const wasOpen = useRef(false);
  const openedServerId = useRef<number | null>(null);
  useEffect(() => {
    if (wasOpen.current && !showSharedOverlay) onClosed?.();
    wasOpen.current = showSharedOverlay;
  }, [showSharedOverlay, onClosed]);
  useEffect(() => {
    if (initialServer && openedServerId.current !== initialServer.id) {
      openedServerId.current = initialServer.id;
      setActiveServer(initialServer);
      manageServerModal.toggle(true);
    }
  }, [initialServer, manageServerModal]);
  const handleDisconnect = useCallback(
    (serverId: number) => {
      const server = mcpServers.find((s) => s.id === serverId);
      if (server) {
        setActiveServer(server);
        manageServerModal.toggle(false);
        authModal.toggle(false);
        disconnectModal.toggle(true);
      }
    },
    [mcpServers, disconnectModal, manageServerModal, authModal]
  );

  const handleConfirmDisconnect = useCallback(async () => {
    if (!activeServer) return;

    setIsDisconnecting(true);
    try {
      await updateMCPServerStatus(
        activeServer.id,
        MCPServerStatus.DISCONNECTED
      );

      toast.success(t("mcpPage.toasts.serverDisconnected"));

      await onChanged();
      disconnectModal.toggle(false);
      setActiveServer(null);
    } catch (error) {
      console.error("Error disconnecting server:", error);
      toast.error(
        error instanceof Error
          ? error.message
          : t("mcpPage.toasts.disconnectFailed")
      );
    } finally {
      setIsDisconnecting(false);
    }
  }, [activeServer, onChanged, disconnectModal, t]);

  const handleDelete = useCallback(
    async (serverId: number) => {
      try {
        await deleteMCPServer(serverId);

        toast.success(t("mcpPage.toasts.serverDeleted"));

        await onChanged();
      } catch (error) {
        console.error("Error deleting server:", error);
        toast.error(
          error instanceof Error
            ? error.message
            : t("mcpPage.toasts.deleteFailed")
        );
        throw error;
      }
    },
    [onChanged, t]
  );

  const handleConfirmDisconnectAndDelete = useCallback(async () => {
    if (!activeServer || isDisconnecting) return;
    setIsDisconnecting(true);
    try {
      await handleDelete(activeServer.id);
      disconnectModal.toggle(false);
      setActiveServer(null);
    } catch {
      // The mutation reports the error; retain the dialog for retry.
    } finally {
      setIsDisconnecting(false);
    }
  }, [activeServer, isDisconnecting, handleDelete, disconnectModal]);

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

  const handleAuthenticate = useCallback(
    (serverId: number) => {
      const server = mcpServers.find((s) => s.id === serverId);
      if (server) {
        setActiveServer(server);
        manageServerModal.toggle(false);
        authModal.toggle(true);
      }
    },
    [mcpServers, authModal, manageServerModal]
  );

  const triggerFetchToolsInPlace = useCallback(
    async (serverId: number) => {
      if (fetchingToolsServerIds.includes(serverId)) {
        return;
      }

      try {
        // Expand tools list immediately so the user sees the skeleton
        onToolsFetching?.(serverId);

        await updateMCPServerStatus(serverId, MCPServerStatus.FETCHING_TOOLS);
        await onChanged();

        await refreshMCPServerTools(serverId);

        toast.success(t("mcpPage.toasts.toolsFetched"));

        await onChanged();
      } catch (error) {
        console.error("Failed to fetch tools:", error);
        toast.error(
          t("mcpPage.toasts.fetchToolsFailed", {
            error:
              error instanceof Error
                ? error.message
                : t("mcpPage.errors.unknown"),
          })
        );
        await onChanged();
      }
    },
    [fetchingToolsServerIds, onChanged, onToolsFetching, t]
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

  return (
    <>
      {children?.({
        add: handleAddServer,
        manage: openManageServerModal,
        authenticate: handleAuthenticate,
        disconnect: handleDisconnect,
        delete: handleDelete,
      })}
      {showSharedOverlay && (
        <div
          className="fixed inset-0 z-modal-overlay bg-mask-03 backdrop-blur-03 pointer-events-none data-[state=open]:animate-in data-[state=open]:fade-in-0"
          data-state="open"
          aria-hidden="true"
        />
      )}
      <authModal.Provider>
        <MCPAuthenticationModal
          mcpServer={currentActiveServer}
          skipOverlay
          onTriggerFetchTools={triggerFetchToolsInPlace}
          onChanged={onChanged}
        />
      </authModal.Provider>

      <manageServerModal.Provider>
        <AddMCPServerModal
          skipOverlay
          activeServer={activeServer}
          onDisconnect={handleDisconnect}
          onServerCreated={onServerCreated}
          handleAuthenticate={handleAuthenticate}
          mutateMcpServers={onChanged}
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
    </>
  );
}
