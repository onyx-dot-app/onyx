import type { ApiResponse, MethodSpec, ToolSnapshot } from "@/lib/tools/types";
import { enrichToolSnapshot, type RawToolSnapshot } from "@/lib/tools/enrich";

// Calls for OpenAPI plugins (custom tools): validate a schema, then create,
// update or delete the tool built from it.

export async function validateToolDefinition(toolData: {
  definition: Record<string, unknown>;
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
  definition: Record<string, unknown>;
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

    const tool: RawToolSnapshot = await response.json();
    return { data: enrichToolSnapshot(tool), error: null };
  } catch (error) {
    console.error("Error creating tool:", error);
    return { data: null, error: "Error creating tool" };
  }
}

type ToolUpdatePayload = {
  name?: string;
  description?: string;
  definition?: Record<string, unknown>;
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

    const updatedTool: RawToolSnapshot = await response.json();
    return { data: enrichToolSnapshot(updatedTool), error: null };
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
