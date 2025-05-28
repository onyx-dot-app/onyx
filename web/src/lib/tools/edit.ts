import { MethodSpec, ToolSnapshot } from "./interfaces";

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
