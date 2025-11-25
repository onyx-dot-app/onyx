"use client";

import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import PageHeader from "@/refresh-components/headers/PageHeader";
import SvgActions from "@/icons/actions";
import { Separator } from "@/components/ui/separator";
import Actionbar from "@/sections/actions/Actionbar";
import MCPActionsList from "./MCPActionsList";
import AddMCPServerModal from "./AddMCPServerModal";
import { refreshMCPServerTools } from "@/lib/mcpService";
import { MCPActionsProvider, useMCPActions } from "./MCPActionsContext";

function MCPActionsPageContent() {
  const {
    mcpServers,
    isLoading,
    popup,
    setPopup,
    mutateMcpServers,
    toolsFetchingServerIds,
    setToolsFetchingServerIds,
    manageServerModal,
    setServerToManage,
  } = useMCPActions();
  const searchParams = useSearchParams();
  const router = useRouter();
  const [isFetchingTools, setIsFetchingTools] = useState(false);

  // Handle OAuth callback - fetch tools when server_id is present
  useEffect(() => {
    const serverId = searchParams.get("server_id");

    // Only process if we have a server_id and haven't processed this one yet
    if (
      serverId &&
      !toolsFetchingServerIds.includes(serverId) &&
      !isFetchingTools
    ) {
      setToolsFetchingServerIds([...toolsFetchingServerIds, serverId]);

      const fetchToolsAfterOAuth = async () => {
        setIsFetchingTools(true);
        try {
          await fetch(
            `/api/admin/mcp/server/${serverId}/status?status=CONNECTED`,
            {
              method: "PATCH",
            }
          );

          await mutateMcpServers();

          // Refresh tools for this server (will be cached by SWR for when user expands)
          await refreshMCPServerTools(parseInt(serverId));
          setPopup({
            message: "Successfully connected to MCP server and fetched tools",
            type: "success",
          });
        } catch (error) {
          console.error("Failed to fetch tools after OAuth:", error);
          setPopup({
            message: `Failed to fetch tools: ${
              error instanceof Error ? error.message : "Unknown error"
            }`,
            type: "error",
          });
        } finally {
          router.replace("/admin/mcp-actions");
          setToolsFetchingServerIds((prev) =>
            prev.filter((id) => id !== serverId)
          );
          setIsFetchingTools(false);
        }
      };

      fetchToolsAfterOAuth();
    }
  }, [
    searchParams,
    isFetchingTools,
    mutateMcpServers,
    setPopup,
    router,
    toolsFetchingServerIds,
    setToolsFetchingServerIds,
  ]);

  const hasActions = mcpServers.length > 0;

  if (isLoading) {
    return (
      <div className="mx-auto container">
        <div className="flex items-center justify-center h-64">
          <div>Loading...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto container">
      {popup}
      <PageHeader
        icon={SvgActions}
        title="MCP Actions"
        description="Connect MCP (Model Context Protocol) server to add custom actions for chats and agents to retrieve specific data or perform predefined tasks."
      />
      <Separator className="my-0 border border-border-01 mb-6" />
      <Actionbar
        hasActions={hasActions}
        onAddMCPServer={() => {
          setServerToManage(null); // Clear any selected server when creating new
          manageServerModal.toggle(true);
        }}
        buttonText="Add MCP Server"
      />
      <MCPActionsList />
      <manageServerModal.Provider>
        <AddMCPServerModal skipOverlay />
      </manageServerModal.Provider>
    </div>
  );
}

export default function MCPActionsPage() {
  return (
    <MCPActionsProvider>
      <MCPActionsPageContent />
    </MCPActionsProvider>
  );
}
