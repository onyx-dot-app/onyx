"use client";

import { useEffect, useRef } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import PageHeader from "@/refresh-components/headers/PageHeader";
import SvgActions from "@/icons/actions";
import { Separator } from "@/components/ui/separator";
import Actionbar from "@/sections/actions/Actionbar";
import MCPActionsList from "./MCPActionsList";
import AddMCPServerModal from "./AddMCPServerModal";
import { refreshMCPServerTools, updateMCPServerStatus } from "@/lib/mcpService";
import { MCPActionsProvider, useMCPActions } from "./MCPActionsContext";

function MCPActionsPageContent() {
  const {
    mcpServers,
    isLoading,
    fetchingToolsServerIds,
    popup,
    setPopup,
    mutateMcpServers,
    manageServerModal,
    setServerToManage,
    setServerToExpand,
  } = useMCPActions();
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
          await updateMCPServerStatus(serverIdInt, "FETCHING_TOOLS");

          await mutateMcpServers();

          router.replace("/admin/mcp-actions");

          // Automatically expand the tools for this server
          setServerToExpand(serverIdInt);

          await refreshMCPServerTools(serverIdInt);

          setPopup({
            message: "Successfully connected and fetched tools",
            type: "success",
          });

          await mutateMcpServers();
        } catch (error) {
          console.error("Failed to fetch tools:", error);
          setPopup({
            message: `Failed to fetch tools: ${
              error instanceof Error ? error.message : "Unknown error"
            }`,
            type: "error",
          });
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
    setPopup,
    setServerToExpand,
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
