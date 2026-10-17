import { ApiResponse, MethodSpec, ToolSnapshot } from "@/lib/tools/types";
import { parseErrorDetail } from "@/lib/fetcher";
import * as yup from "yup";
import type {
  ToolUserPreferencesRequest,
  ToolUserPreferencesResponse,
} from "@/lib/tools/types";

export async function updateToolUserPreferences(
  toolId: number,
  preferences: ToolUserPreferencesRequest
): Promise<ToolUserPreferencesResponse> {
  const response = await fetch(`/api/tool/${toolId}/preferences`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(preferences),
  });
  if (!response.ok) {
    throw new Error(
      await parseErrorDetail(response, "Failed to save plugin preferences")
    );
  }
  return yup
    .object({ enabled_in_chat: yup.boolean().defined() })
    .validateSync(await response.json(), { strict: true });
}

export interface ToolStatusUpdateRequest {
  tool_ids: number[];
  enabled: boolean;
}

export interface ToolStatusUpdateResponse {
  updated_count: number;
  tool_ids: number[];
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
    } satisfies ToolStatusUpdateRequest),
  });

  if (!response.ok) {
    throw new Error(
      await parseErrorDetail(response, "Failed to update tool status")
    );
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

    // Mirrors `ValidateToolResponse` in backend/onyx/server/features/tool/api.py.
    const responseJson: { methods: MethodSpec[] } = await response.json();
    return { data: responseJson.methods, error: null };
  } catch (error) {
    console.error("Error validating tool:", error);
    return { data: null, error: "Unexpected error validating tool definition" };
  }
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

type ToolUpdatePayload = {
  name?: string;
  description?: string;
  definition?: Record<string, any>;
  custom_headers?: { key: string; value: string }[] | null;
  passthrough_auth?: boolean;
  oauth_config_id?: number | null;
};

export async function updateCustomTool(
  toolId: number,
  toolData: ToolUpdatePayload
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
