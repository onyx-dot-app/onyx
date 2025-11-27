"use client";
import ActionCard from "@/sections/actions/ActionCard";
import { getMCPServerIcon } from "@/lib/mcpUtils";
import { MCPActionStatus, MCPServerStatus, MCPServerWithStatus } from "./types";
import MCPAuthenticationModal from "./modals/MCPAuthenticationModal";
import DisconnectMCPModal from "./modals/DisconnectMCPModal";
import { useMCPActions } from "./MCPActionsContext";

export default function MCPActionsList() {
  const {
    mcpServers,
    authModal,
    disconnectModal,
    selectedServer,
    serverToDisconnect,
    serverToExpand,
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

  // Determine MCP action status based on server status field
  const getStatus = (server: MCPServerWithStatus): MCPActionStatus => {
    if (server.status === MCPServerStatus.CONNECTED) {
      return MCPActionStatus.CONNECTED;
    } else if (
      server.status === MCPServerStatus.AWAITING_AUTH ||
      server.status === MCPServerStatus.CREATED
    ) {
      return MCPActionStatus.PENDING;
    } else if (server.status === MCPServerStatus.FETCHING_TOOLS) {
      return MCPActionStatus.FETCHING;
    }
    return MCPActionStatus.DISCONNECTED;
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
              initialExpanded={server.id === serverToExpand}
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
