"use client";

import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import useSWR from "swr";
import PageHeader from "@/refresh-components/headers/PageHeader";
import SvgActions from "@/icons/actions";
import { Separator } from "@/components/ui/separator";
import Actionbar from "@/sections/actions/Actionbar";
import { MCPServersResponse } from "@/lib/tools/interfaces";
import MCPActionsList from "./MCPActionsList";
import AddMCPServerModal from "./AddMCPServerModal";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { refreshMCPServerTools } from "@/lib/mcpService";

export default function MCPActionsPage() {
  const { popup, setPopup } = usePopup();
  const addServerModal = useCreateModal();
  const searchParams = useSearchParams();
  const router = useRouter();
  const [isFetchingTools, setIsFetchingTools] = useState(false);
  const [toolsFetchingServerIds, setToolsFetchingServerIds] = useState<
    string[]
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

          router.replace("/admin/mcp-actions");

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
          setToolsFetchingServerIds((prev) =>
            prev.filter((id) => id !== serverId)
          );
          setIsFetchingTools(false);
        }
      };

      fetchToolsAfterOAuth();
    }
  }, [searchParams, isFetchingTools, mutateMcpServers, setPopup, router]);

  const mcpServers = (mcpData?.mcp_servers || []) as any[];
  const isLoading = isMcpLoading;
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
        onAddMCPServer={() => addServerModal.toggle(true)}
        buttonText="Add MCP Server"
      />
      <MCPActionsList
        mcpServers={mcpServers}
        mutateMcpServers={mutateMcpServers}
        setPopup={setPopup}
        toolsFetchingServerIds={toolsFetchingServerIds}
      />
      <addServerModal.Provider>
        <AddMCPServerModal
          mutateMcpServers={mutateMcpServers}
          setPopup={setPopup}
        />
      </addServerModal.Provider>
    </div>
  );
}
