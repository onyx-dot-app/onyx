"use client";

import { useMemo } from "react";
import useSWR from "swr";
import PageHeader from "@/refresh-components/headers/PageHeader";
import SvgActions from "@/icons/actions";
import { Separator } from "@/components/ui/separator";
import Actionbar from "@/sections/actions/Actionbar";
import { MCPServersResponse } from "@/lib/tools/interfaces";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import MCPActionsList from "./MCPActionsList";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { usePopup } from "@/components/admin/connectors/Popup";

export default function MCPActionsPage() {
  const { popup, setPopup } = usePopup();
  // Fetch MCP servers
  const {
    data: mcpData,
    isLoading: isMcpLoading,
    mutate: mutateMcpServers,
  } = useSWR<MCPServersResponse>(
    "/api/admin/mcp/servers",
    errorHandlingFetcher
  );

  // Fetch all MCP tools (includes both enabled and disabled)
  const {
    data: toolsData,
    isLoading: isToolsLoading,
    mutate: mutateTools,
  } = useSWR<ToolSnapshot[]>("/api/admin/mcp/tools", errorHandlingFetcher);

  // Group tools by server ID
  const toolsByServer = useMemo(() => {
    if (!toolsData) return {};

    return toolsData.reduce(
      (acc, tool) => {
        if (tool.mcp_server_id) {
          acc[tool.mcp_server_id] = [...(acc[tool.mcp_server_id] || []), tool];
        }
        return acc;
      },
      {} as Record<number, ToolSnapshot[]>
    );
  }, [toolsData]);

  const mcpServers = mcpData?.mcp_servers || [];
  const isLoading = isMcpLoading || isToolsLoading;
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
        onAddMCPServer={() => console.log("Add MCP Server clicked")}
        buttonText="Add MCP Server"
      />
      <MCPActionsList
        mcpServers={mcpServers}
        toolsByServer={toolsByServer}
        mutateMcpServers={mutateMcpServers}
        mutateTools={mutateTools}
        setPopup={setPopup}
      />
    </div>
  );
}
