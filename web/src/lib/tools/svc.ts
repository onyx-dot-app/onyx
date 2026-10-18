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
