import { AgentUpsertParameters, AgentUpsertRequest } from "@/lib/agents/types";

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
async function parseErrorDetail(res: Response, fallback: string) {
  try {
    const body = await res.json();
    return (body?.detail as string) ?? fallback;
  } catch {
    return fallback;
  }
}

// ── Agent CRUD ───────────────────────────────────────────────────────────────

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
  id: number,
  params: AgentUpsertParameters
): Promise<Response> {
  return fetch(`/api/persona/${id}`, {
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

/**
 * Uploads an agent avatar image. Returns the server-assigned file ID on
 * success, or null if the upload fails.
 */
export async function uploadFile(file: File): Promise<string | null> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch("/api/admin/persona/upload-image", {
    method: "POST",
    body: formData,
    credentials: "include",
  });
  if (!res.ok) {
    return null;
  }
  return ((await res.json()) as { file_id: string }).file_id;
}

// ── Sharing & visibility ─────────────────────────────────────────────────────

/**
 * Updates the agent's sharing settings (users, groups, public flag, labels).
 * Group sharing is EE-only — groupIds are silently dropped when enterprise
 * features are disabled. Returns an error string on failure, null on success.
 */
export async function updateAgentSharedStatus(
  agentId: number,
  userIds: string[],
  groupIds: number[],
  isPublic: boolean | undefined,
  isPaidEnterpriseFeaturesEnabled: boolean,
  labelIds?: number[]
): Promise<string | null> {
  if (!isPaidEnterpriseFeaturesEnabled && groupIds.length > 0) {
    console.error(
      "updateAgentSharedStatus: groupIds provided but enterprise features are disabled. " +
        "Group sharing is an EE-only feature. Discarding groupIds."
    );
  }

  try {
    const res = await fetch(`/api/persona/${agentId}/share`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_ids: userIds,
        group_ids: isPaidEnterpriseFeaturesEnabled ? groupIds : undefined,
        is_public: isPublic,
        label_ids: labelIds,
      }),
    });
    if (res.ok) return null;
    return (
      ((await res.json()) as { detail?: string }).detail ?? "Unknown error"
    );
  } catch {
    return "Network error. Please check your connection and try again.";
  }
}

// ── Featured / listed / display priority ─────────────────────────────────────

/**
 * Sets the agent's featured status. Admin-only endpoint.
 * Returns an error string on failure, null on success.
 */
export async function updateAgentFeaturedStatus(
  agentId: number,
  isFeatured: boolean
): Promise<string | null> {
  try {
    const res = await fetch(`/api/admin/persona/${agentId}/featured`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_featured: isFeatured }),
    });
    if (res.ok) return null;
    return (
      ((await res.json()) as { detail?: string }).detail ?? "Unknown error"
    );
  } catch {
    return "Network error. Please check your connection and try again.";
  }
}

/** Flips the agent's featured status. Admin-only. Throws on failure. */
export async function toggleAgentFeatured(
  agentId: number,
  currentlyFeatured: boolean
): Promise<void> {
  const res = await fetch(`/api/admin/persona/${agentId}/featured`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_featured: !currentlyFeatured }),
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
export async function toggleAgentListed(
  agentId: number,
  currentlyListed: boolean
): Promise<void> {
  const res = await fetch(`/api/admin/persona/${agentId}/listed`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_listed: !currentlyListed }),
    credentials: "include",
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to toggle visibility"));
  }
}

/**
 * Bulk-updates display order for agents in the admin panel. Used after
 * drag-and-drop reordering. Throws on failure.
 */
export async function updateAgentDisplayPriorities(
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

// ── Pinned agents ─────────────────────────────────────────────────────────────

/**
 * Replaces the user's full ordered list of pinned agents. The order of the
 * array determines sidebar display order. Throws on failure.
 */
export async function pinAgents(pinnedAgentIds: number[]): Promise<void> {
  const res = await fetch(`/api/user/pinned-assistants`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    // TODO(ENG-3766): rename to agent
    body: JSON.stringify({ ordered_assistant_ids: pinnedAgentIds }),
  });
  if (!res.ok) {
    throw new Error("Failed to update pinned assistants");
  }
}
