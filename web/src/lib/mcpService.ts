/**
 * Service layer for MCP (Model Context Protocol) related API calls
 */

import {
  MCPServerWithStatus,
  MCPServerCreateRequest,
} from "@/app/admin/mcp-actions/types";

export interface ToolStatusUpdateRequest {
  tool_ids: number[];
  enabled: boolean;
}

export interface ToolStatusUpdateResponse {
  updated_count: number;
  tool_ids: number[];
}

/**
 * Delete an MCP server
 */
export async function deleteMCPServer(serverId: number): Promise<void> {
  const response = await fetch(`/api/admin/mcp/server/${serverId}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || "Failed to delete MCP server");
  }
}

/**
 * Refresh/sync tools from an MCP server
 */
export async function refreshMCPServerTools(serverId: number): Promise<void> {
  const response = await fetch(`/api/admin/mcp/server/${serverId}/tools`);

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || "Failed to refresh tools");
  }
}

/**
 * Update status (enable/disable) for one or more tools
 */
export async function updateToolsStatus(
  toolIds: number[],
  enabled: boolean
): Promise<ToolStatusUpdateResponse> {
  const response = await fetch("/api/admin/tool/status", {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      tool_ids: toolIds,
      enabled: enabled,
    } as ToolStatusUpdateRequest),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || "Failed to update tool status");
  }

  return await response.json();
}

/**
 * Update status for a single tool
 */
export async function updateToolStatus(
  toolId: number,
  enabled: boolean
): Promise<ToolStatusUpdateResponse> {
  return updateToolsStatus([toolId], enabled);
}

/**
 * Disable all tools for a specific MCP server
 */
export async function disableAllServerTools(
  toolIds: number[]
): Promise<ToolStatusUpdateResponse> {
  return updateToolsStatus(toolIds, false);
}

/**
 * Create a new MCP server with basic information
 */
export async function createMCPServer(
  data: MCPServerCreateRequest
): Promise<MCPServerWithStatus> {
  const response = await fetch("/api/admin/mcp/server", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || "Failed to create MCP server");
  }

  return await response.json();
}
