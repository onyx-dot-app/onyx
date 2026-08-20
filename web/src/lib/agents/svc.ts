import {
  AgentShareUpdatePayload,
  AgentUpsertParameters,
  AgentUpsertRequest,
} from "@/lib/agents/types";

/**
 * Maps client-facing AgentUpsertParameters to the wire shape expected by the
 * API. `display_priority` is always sent as null because ordering is managed
 * server-side via the dedicated display-priorities endpoint.
 */
function buildAgentUpsertRequest(
  params: AgentUpsertParameters
): AgentUpsertRequest {
  return {
    name: params.name,
    description: params.description,
    system_prompt: params.system_prompt,
    task_prompt: params.task_prompt,
    document_set_ids: params.document_set_ids,
    is_public: params.is_public,
    uploaded_image_id: params.uploaded_image_id,
    icon_name: params.icon_name,
    groups: params.groups,
    users: params.users,
    tool_ids: params.tool_ids,
    remove_image: params.remove_image,
    search_start_date: params.search_start_date,
    datetime_aware: params.datetime_aware,
    is_featured: params.is_featured ?? false,
    default_model_configuration_id:
      params.default_model_configuration_id ?? null,
    starter_messages: params.starter_messages ?? null,
    display_priority: null,
    label_ids: params.label_ids ?? null,
    user_file_ids: params.user_file_ids ?? null,
    replace_base_system_prompt: params.replace_base_system_prompt,
    hierarchy_node_ids: params.hierarchy_node_ids ?? [],
    document_ids: params.document_ids ?? [],
  };
}

/** Extracts `detail` from a non-OK JSON response body, falling back to `fallback`. */
export async function parseErrorDetail(res: Response, fallback: string) {
  try {
    const body = await res.json();
    return typeof body?.detail === "string" ? body.detail : fallback;
  } catch {
    return fallback;
  }
}

// Agent CRUD

/**
 * Creates a new agent. Returns the raw Response so the caller can read the
 * created agent's ID from the body.
 */
export async function createAgent(
  params: AgentUpsertParameters
): Promise<Response> {
  return fetch("/api/persona", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildAgentUpsertRequest(params)),
    credentials: "include",
  });
}

/**
 * Updates an existing agent. Returns the raw Response so the caller can
 * inspect the updated fields.
 */
export async function updateAgent(
  agentId: number,
  params: AgentUpsertParameters
): Promise<Response> {
  return fetch(`/api/persona/${agentId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildAgentUpsertRequest(params)),
    credentials: "include",
  });
}

/** Deletes an agent. Throws on failure. */
export async function deleteAgent(agentId: number): Promise<void> {
  const res = await fetch(`/api/persona/${agentId}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to delete agent"));
  }
}

/** Flips the agent's featured status. Admin-only. Throws on failure. */
export async function featureAgent(
  agentId: number,
  shouldFeature: boolean
): Promise<void> {
  const res = await fetch(`/api/admin/persona/${agentId}/featured`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_featured: shouldFeature }),
    credentials: "include",
  });
  if (!res.ok) {
    throw new Error(
      await parseErrorDetail(res, "Failed to toggle featured status")
    );
  }
}

/**
 * Flips the agent's listed status. Unlisted agents are hidden from the
 * explore list but remain accessible via direct link. Throws on failure.
 */
export async function listAgent(
  agentId: number,
  shouldList: boolean
): Promise<void> {
  const res = await fetch(`/api/admin/persona/${agentId}/listed`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_listed: shouldList }),
    credentials: "include",
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to toggle visibility"));
  }
}

/**
 * Replaces the user's full ordered list of pinned agents. The order of the
 * array determines sidebar display order. Throws on failure.
 */
export async function pinAgents(pinnedAgentIds: number[]): Promise<void> {
  const res = await fetch(`/api/user/pinned-assistants`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ordered_assistant_ids: pinnedAgentIds }),
  });
  if (!res.ok) {
    throw new Error("Failed to update pinned assistants");
  }
}

// Sharing

/**
 * Writes an agent's shares verbatim. Whether the caller is allowed to set
 * `group_shares` is a plan question, so it is decided before the payload gets
 * here — see {@link useUpdateAgentShares}, which is what callers should use.
 * Returns an error string, or null on success.
 */
export async function updateAgentShares(
  agentId: number,
  payload: AgentShareUpdatePayload
): Promise<string | null> {
  try {
    const res = await fetch(`/api/persona/${agentId}/share`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      credentials: "include",
    });

    if (res.ok) return null;

    return await parseErrorDetail(res, "Failed to update agent shares");
  } catch {
    return "Network error. Please check your connection and try again.";
  }
}

export async function transferAgentOwnership(
  agentId: number,
  payload:
    | { new_owner_user_id: string; new_owner_group_id?: never }
    | { new_owner_group_id: number; new_owner_user_id?: never }
): Promise<string | null> {
  try {
    const res = await fetch(`/api/persona/${agentId}/transfer-ownership`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      credentials: "include",
    });

    if (res.ok) {
      return null;
    }

    return await parseErrorDetail(res, "Failed to transfer ownership");
  } catch {
    return "Network error. Please check your connection and try again.";
  }
}

export async function removeSelfFromAgentShares(
  agentId: number
): Promise<string | null> {
  try {
    const res = await fetch(`/api/persona/${agentId}/share/me`, {
      method: "DELETE",
      credentials: "include",
    });

    if (res.ok) {
      return null;
    }

    return await parseErrorDetail(res, "Failed to remove access");
  } catch {
    return "Network error. Please check your connection and try again.";
  }
}

// Admin

/**
 * Bulk-updates display order for agents in the admin panel. Used after
 * drag-and-drop reordering. Throws on failure.
 */
export async function updateAgentDisplayOrder(
  displayPriorityMap: Record<string, number>
): Promise<void> {
  const res = await fetch("/api/admin/agents/display-priorities", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_priority_map: displayPriorityMap }),
  });
  if (!res.ok) {
    throw new Error(
      await parseErrorDetail(res, "Failed to update agent order")
    );
  }
}
