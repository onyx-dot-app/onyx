import { ApiResponse, MethodSpec } from "@/lib/tools/types";
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
