/** API helpers for the Groups pages. */

const USER_GROUP_URL = "/api/manage/admin/user-group";

async function renameGroup(groupId: number, newName: string): Promise<void> {
  const res = await fetch(`${USER_GROUP_URL}/rename`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: groupId, name: newName }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(
      detail?.detail ?? `Failed to rename group: ${res.statusText}`
    );
  }
}

async function createGroup(
  name: string,
  userIds: string[],
  ccPairIds: number[] = []
): Promise<number> {
  const res = await fetch(USER_GROUP_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      user_ids: userIds,
      cc_pair_ids: ccPairIds,
    }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(
      detail?.detail ?? `Failed to create group: ${res.statusText}`
    );
  }
  const group = await res.json();
  return group.id;
}

async function deleteGroup(groupId: number): Promise<void> {
  const res = await fetch(`${USER_GROUP_URL}/${groupId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(
      detail?.detail ?? `Failed to delete group: ${res.statusText}`
    );
  }
}

// ---------------------------------------------------------------------------
// Agent (persona) sharing — managed from the persona side
// ---------------------------------------------------------------------------

async function updateAgentGroupSharing(
  groupId: number,
  initialAgentIds: number[],
  currentAgentIds: number[]
): Promise<void> {
  const initialSet = new Set(initialAgentIds);
  const currentSet = new Set(currentAgentIds);

  const added_agent_ids = currentAgentIds.filter((id) => !initialSet.has(id));
  const removed_agent_ids = initialAgentIds.filter((id) => !currentSet.has(id));

  if (added_agent_ids.length === 0 && removed_agent_ids.length === 0) return;

  const res = await fetch(`${USER_GROUP_URL}/${groupId}/agents`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ added_agent_ids, removed_agent_ids }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(
      detail?.detail ?? `Failed to update agent sharing: ${res.statusText}`
    );
  }
}

// ---------------------------------------------------------------------------
// Document set sharing — managed from the document set side
// ---------------------------------------------------------------------------

interface DocumentSetSummary {
  id: number;
  description: string;
  cc_pair_summaries: { id: number }[];
  federated_connector_summaries: { id: number }[];
  is_public: boolean;
  users: string[];
  groups: number[];
}

async function updateDocSetGroupSharing(
  groupId: number,
  initialDocSetIds: number[],
  currentDocSetIds: number[]
): Promise<void> {
  const initialSet = new Set(initialDocSetIds);
  const currentSet = new Set(currentDocSetIds);

  const added = currentDocSetIds.filter((id) => !initialSet.has(id));
  const removed = initialDocSetIds.filter((id) => !currentSet.has(id));

  if (added.length === 0 && removed.length === 0) return;

  // Fetch all document sets to get their current state
  const allRes = await fetch("/api/manage/document-set");
  if (!allRes.ok) {
    throw new Error("Failed to fetch document sets");
  }
  const allDocSets: DocumentSetSummary[] = await allRes.json();
  const docSetMap = new Map(allDocSets.map((ds) => [ds.id, ds]));

  for (const dsId of added) {
    const ds = docSetMap.get(dsId);
    if (!ds) {
      throw new Error(`Document set ${dsId} not found`);
    }
    const updatedGroups = ds.groups.includes(groupId)
      ? ds.groups
      : [...ds.groups, groupId];
    const res = await fetch("/api/manage/admin/document-set", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: ds.id,
        description: ds.description,
        cc_pair_ids: ds.cc_pair_summaries.map((cc) => cc.id),
        federated_connectors: ds.federated_connector_summaries.map((fc) => ({
          federated_connector_id: fc.id,
        })),
        is_public: ds.is_public,
        users: ds.users,
        groups: updatedGroups,
      }),
    });
    if (!res.ok) {
      throw new Error(`Failed to add group to document set ${dsId}`);
    }
  }

  for (const dsId of removed) {
    const ds = docSetMap.get(dsId);
    if (!ds) {
      throw new Error(`Document set ${dsId} not found`);
    }
    const updatedGroups = ds.groups.filter((id) => id !== groupId);
    const res = await fetch("/api/manage/admin/document-set", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: ds.id,
        description: ds.description,
        cc_pair_ids: ds.cc_pair_summaries.map((cc) => cc.id),
        federated_connectors: ds.federated_connector_summaries.map((fc) => ({
          federated_connector_id: fc.id,
        })),
        is_public: ds.is_public,
        users: ds.users,
        groups: updatedGroups,
      }),
    });
    if (!res.ok) {
      throw new Error(`Failed to remove group from document set ${dsId}`);
    }
  }
}

// ---------------------------------------------------------------------------
// Token rate limits — create / update / delete
// ---------------------------------------------------------------------------

interface TokenLimitPayload {
  tokenBudget: number | null;
  periodHours: number | null;
}

interface ExistingTokenLimit {
  token_id: number;
  enabled: boolean;
  token_budget: number;
  period_hours: number;
}

async function saveTokenLimits(
  groupId: number,
  limits: TokenLimitPayload[],
  existing: ExistingTokenLimit[]
): Promise<void> {
  // Filter to only valid (non-null) limits
  const validLimits = limits.filter(
    (l): l is { tokenBudget: number; periodHours: number } =>
      l.tokenBudget != null && l.periodHours != null
  );

  // Update existing limits (match by index position)
  const toUpdate = Math.min(validLimits.length, existing.length);
  for (let i = 0; i < toUpdate; i++) {
    const limit = validLimits[i]!;
    const existingLimit = existing[i]!;
    const updateRes = await fetch(
      `/api/admin/token-rate-limits/rate-limit/${existingLimit.token_id}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: existingLimit.enabled,
          token_budget: limit.tokenBudget,
          period_hours: limit.periodHours,
        }),
      }
    );
    if (!updateRes.ok) {
      throw new Error(
        `Failed to update token rate limit ${existingLimit.token_id}`
      );
    }
  }

  // Create new limits beyond existing count
  for (let i = toUpdate; i < validLimits.length; i++) {
    const limit = validLimits[i]!;
    const createRes = await fetch(
      `/api/admin/token-rate-limits/user-group/${groupId}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: true,
          token_budget: limit.tokenBudget,
          period_hours: limit.periodHours,
        }),
      }
    );
    if (!createRes.ok) {
      throw new Error("Failed to create token rate limit");
    }
  }

  // Delete excess existing limits
  for (let i = toUpdate; i < existing.length; i++) {
    const existingLimit = existing[i]!;
    const deleteRes = await fetch(
      `/api/admin/token-rate-limits/rate-limit/${existingLimit.token_id}`,
      { method: "DELETE" }
    );
    if (!deleteRes.ok) {
      throw new Error(
        `Failed to delete token rate limit ${existingLimit.token_id}`
      );
    }
  }
}

export {
  USER_GROUP_URL,
  renameGroup,
  createGroup,
  deleteGroup,
  updateAgentGroupSharing,
  updateDocSetGroupSharing,
  saveTokenLimits,
};
