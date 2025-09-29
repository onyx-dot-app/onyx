import {
  MethodSpec,
  ToolSnapshot,
  MCPServersResponse,
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
} from "./interfaces";

interface ApiResponse<T> {
  data: T | null;
  error: string | null;
}

export async function createCustomTool(toolData: {
  name: string;
  description?: string;
  definition: Record<string, any>;
  custom_headers: { key: string; value: string }[];
  passthrough_auth: boolean;
}): Promise<ApiResponse<ToolSnapshot>> {
  try {
    const response = await fetch("/api/admin/tool/custom", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(toolData),
    });

    if (!response.ok) {
      const errorDetail = (await response.json()).detail;
      return { data: null, error: `Failed to create tool: ${errorDetail}` };
    }

    const tool: ToolSnapshot = await response.json();
    return { data: tool, error: null };
  } catch (error) {
    console.error("Error creating tool:", error);
    return { data: null, error: "Error creating tool" };
  }
}

export async function updateCustomTool(
  toolId: number,
  toolData: {
    name?: string;
    description?: string;
    definition?: Record<string, any>;
    custom_headers: { key: string; value: string }[];
    passthrough_auth: boolean;
  }
): Promise<ApiResponse<ToolSnapshot>> {
  try {
    const response = await fetch(`/api/admin/tool/custom/${toolId}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(toolData),
    });

    if (!response.ok) {
      const errorDetail = (await response.json()).detail;
      return { data: null, error: `Failed to update tool: ${errorDetail}` };
    }

    const updatedTool: ToolSnapshot = await response.json();
    return { data: updatedTool, error: null };
  } catch (error) {
    console.error("Error updating tool:", error);
    return { data: null, error: "Error updating tool" };
  }
}

export async function deleteCustomTool(
  toolId: number
): Promise<ApiResponse<boolean>> {
  try {
    const response = await fetch(`/api/admin/tool/custom/${toolId}`, {
      method: "DELETE",
      headers: {
        "Content-Type": "application/json",
      },
    });

    if (!response.ok) {
      const errorDetail = (await response.json()).detail;
      return { data: false, error: `Failed to delete tool: ${errorDetail}` };
    }

    return { data: true, error: null };
  } catch (error) {
    console.error("Error deleting tool:", error);
    return { data: false, error: "Error deleting tool" };
  }
}

export async function validateToolDefinition(toolData: {
  definition: Record<string, any>;
}): Promise<ApiResponse<MethodSpec[]>> {
  try {
    const response = await fetch(`/api/admin/tool/custom/validate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(toolData),
    });

    if (!response.ok) {
      const errorDetail = (await response.json()).detail;
      return { data: null, error: errorDetail };
    }

    const responseJson = await response.json();
    return { data: responseJson.methods, error: null };
  } catch (error) {
    console.error("Error validating tool:", error);
    return { data: null, error: "Unexpected error validating tool definition" };
  }
}

interface MCPServerCreateResponse {
  server_id: number;
  server_name: string;
  server_url: string;
  auth_type: string;
  auth_performer: string;
  is_authenticated: boolean;
}

interface MCPToolsUpdateResponse {
  server_id: number;
  updated_tools: number;
}

export async function createMCPServer(serverData: {
  name: string;
  description?: string;
  server_url: string;
  transport: string;
  auth_type: MCPAuthenticationType;
  auth_performer: MCPAuthenticationPerformer;
  api_token?: string;
  oauth_client_id?: string;
  oauth_client_secret?: string;
  auth_template?: any;
  admin_credentials?: Record<string, string>;
  existing_server_id?: number;
}): Promise<ApiResponse<MCPServerCreateResponse>> {
  try {
    const response = await fetch("/api/admin/mcp/servers/create", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(serverData),
    });

    if (!response.ok) {
      const errorDetail = (await response.json()).detail;
      return {
        data: null,
        error: `Failed to create MCP server: ${errorDetail}`,
      };
    }

    const result: MCPServerCreateResponse = await response.json();
    return { data: result, error: null };
  } catch (error) {
    console.error("Error creating MCP server:", error);
    return { data: null, error: `Error creating MCP server: ${error}` };
  }
}

export async function attachMCPTools(toolsData: {
  server_id: number;
  selected_tools: string[];
}): Promise<ApiResponse<MCPToolsUpdateResponse>> {
  try {
    const response = await fetch("/api/admin/mcp/servers/update", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(toolsData),
    });

    if (!response.ok) {
      const errorDetail = (await response.json()).detail;
      return { data: null, error: `Failed to attach tools: ${errorDetail}` };
    }

    const result: MCPToolsUpdateResponse = await response.json();
    return { data: result, error: null };
  } catch (error) {
    console.error("Error attaching MCP tools:", error);
    return { data: null, error: "Error attaching MCP tools" };
  }
}

export async function fetchMCPServers(): Promise<
  ApiResponse<MCPServersResponse>
> {
  try {
    const response = await fetch("/api/admin/mcp/servers", {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
      },
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(
        `HTTP error! status: ${response.status}, message: ${errorText}`
      );
    }

    const result: MCPServersResponse = await response.json();
    return { data: result, error: null };
  } catch (error) {
    console.error("Error fetching MCP servers:", error);
    return { data: null, error: "Error fetching MCP servers" };
  }
}

export async function deleteMCPServer(
  serverId: string | number
): Promise<ApiResponse<{ success: boolean }>> {
  try {
    const response = await fetch(`/api/admin/mcp/server/${serverId}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(
        `HTTP error! status: ${response.status}, message: ${errorText}`
      );
    }
    const result = (await response.json()) as { success: boolean };
    return { data: result, error: null };
  } catch (error) {
    console.error("Error deleting MCP server:", error);
    return { data: null, error: "Error deleting MCP server" };
  }
}
