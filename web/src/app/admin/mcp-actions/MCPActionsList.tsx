"use client";
import ActionCard from "@/sections/actions/ActionCard";
import { getMCPServerIcon } from "@/lib/mcpUtils";
import { MCPActionStatus } from "./types";
import MCPAuthenticationModal from "./MCPAuthenticationModal";
import DisconnectMCPModal from "./DisconnectMCPModal";
import { useMCPActions } from "./MCPActionsContext";

export default function MCPActionsList() {
  const {
    mcpServers,
    authModal,
    disconnectModal,
    selectedServer,
    serverToDisconnect,
    isDisconnecting,
    showSharedOverlay,
    handleDisconnect,
    handleManage,
    handleEdit,
    handleDelete,
    handleAuthenticate,
    handleReconnect,
    handleToolToggle,
    handleRefreshTools,
    handleDisableAllTools,
    handleConfirmDisconnect,
    handleConfirmDisconnectAndDelete,
  } = useMCPActions();

  // Determine status based on server status field
  const getStatus = (server: any): MCPActionStatus => {
    if (server.status === "CONNECTED") {
      return "connected";
    } else if (
      server.status === "AWAITING_AUTH" ||
      server.status === "CREATED"
    ) {
      return "pending";
    } else if (server.status === "FETCHING_TOOLS") {
      return "fetching";
    }
    return "disconnected";
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
            />
          );
        })}

        <authModal.Provider>
          <MCPAuthenticationModal mcpServer={selectedServer} skipOverlay />
        </authModal.Provider>

        <DisconnectMCPModal
          isOpen={disconnectModal.isOpen}
          onClose={() => disconnectModal.toggle(false)}
          server={serverToDisconnect}
          onConfirmDisconnect={handleConfirmDisconnect}
          onConfirmDisconnectAndDelete={handleConfirmDisconnectAndDelete}
          isDisconnecting={isDisconnecting}
          skipOverlay
        />
      </div>
    </>
  );
}
