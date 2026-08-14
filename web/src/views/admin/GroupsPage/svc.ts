/** API helpers for the Groups pages. */

import { SWR_KEYS } from "@/lib/swr-keys";

const USER_GROUP_URL = SWR_KEYS.adminUserGroups;

// Logs an unparseable body — without it a proxy's HTML 502 is indistinguishable from a
// clean API error at the call site.
async function responseError(res: Response, action: string): Promise<Error> {
  try {
    const detail = (await res.json())?.detail;
    if (detail) return new Error(detail);
  } catch (err) {
    console.error(`${action}: unparseable error body`, res.status, err);
  }
  return new Error(`${action}: ${res.statusText}`);
}

async function renameGroup(groupId: number, newName: string): Promise<void> {
  const res = await fetch(`${USER_GROUP_URL}/rename`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: groupId, name: newName }),
  });
  if (!res.ok) {
    throw await responseError(res, "Failed to rename group");
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
    throw await responseError(res, "Failed to create group");
  }
  const group = await res.json();
  return group.id;
}

async function updateGroup(
  groupId: number,
  userIds: string[],
  ccPairIds: number[]
): Promise<void> {
  const res = await fetch(`${USER_GROUP_URL}/${groupId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_ids: userIds,
      cc_pair_ids: ccPairIds,
    }),
  });
  if (!res.ok) {
    throw await responseError(res, "Failed to update group");
  }
}

async function setGroupIncognito(
  groupId: number,
  enabled: boolean
): Promise<void> {
  const res = await fetch(`${USER_GROUP_URL}/${groupId}/incognito`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(
      detail?.detail ?? `Failed to update incognito access: ${res.statusText}`
    );
  }
}

async function deleteGroup(groupId: number): Promise<void> {
  const res = await fetch(`${USER_GROUP_URL}/${groupId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw await responseError(res, "Failed to delete group");
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
    throw await responseError(res, "Failed to update agent sharing");
  }
}

// ---------------------------------------------------------------------------
// Document set sharing
// ---------------------------------------------------------------------------

// Written from the group's side: the document-set route needs MANAGE_DOCUMENT_SETS,
// which a groups admin doesn't hold.
async function updateDocSetGroupSharing(
  groupId: number,
  initialDocSetIds: number[],
  currentDocSetIds: number[]
): Promise<void> {
  const initialSet = new Set(initialDocSetIds);
  const currentSet = new Set(currentDocSetIds);

  const added_document_set_ids = currentDocSetIds.filter(
    (id) => !initialSet.has(id)
  );
  const removed_document_set_ids = initialDocSetIds.filter(
    (id) => !currentSet.has(id)
  );

  if (
    added_document_set_ids.length === 0 &&
    removed_document_set_ids.length === 0
  ) {
    return;
  }

  const res = await fetch(`${USER_GROUP_URL}/${groupId}/document-sets`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ added_document_set_ids, removed_document_set_ids }),
  });
  if (!res.ok) {
    throw await responseError(res, "Failed to update document set sharing");
  }
}

// ---------------------------------------------------------------------------
// Token rate limits — create / update / delete
// ---------------------------------------------------------------------------

const HOURS_PER_DAY = 24;

interface TokenLimitPayload {
  tokenId?: number | null;
  enabled?: boolean;
  tokenBudget: number | null;
  periodDays: number | null;
  costBudgetDollars: number | null;
}

interface ExistingTokenLimit {
  token_id: number;
  enabled: boolean;
  token_budget: number | null;
  period_hours: number;
  cost_budget_cents: number | null;
}

interface ValidTokenLimit {
  tokenId: number | null;
  enabled: boolean;
  tokenBudget: number | null;
  periodDays: number;
  costBudgetCents: number | null;
}

async function saveTokenLimits(
  groupId: number,
  limits: TokenLimitPayload[],
  existing: ExistingTokenLimit[]
): Promise<void> {
  const validLimits: ValidTokenLimit[] = limits
    .map((l) => {
      const costBudgetCents =
        l.costBudgetDollars != null
          ? Math.round(l.costBudgetDollars * 100)
          : null;
      return {
        tokenId: l.tokenId ?? null,
        enabled: l.enabled ?? true,
        tokenBudget: l.tokenBudget,
        periodDays: l.periodDays,
        costBudgetCents,
      };
    })
    .filter(
      (l): l is ValidTokenLimit =>
        l.periodDays != null &&
        (l.tokenBudget != null || l.costBudgetCents != null)
    );

  for (const limit of validLimits.filter((item) => item.tokenId !== null)) {
    const updateRes = await fetch(
      `/api/admin/token-rate-limits/user-group/${groupId}/rate-limit/${limit.tokenId}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: limit.enabled,
          token_budget: limit.tokenBudget,
          period_hours: limit.periodDays * HOURS_PER_DAY,
          cost_budget_cents: limit.costBudgetCents,
        }),
      }
    );
    if (!updateRes.ok) {
      throw new Error(`Failed to update token rate limit ${limit.tokenId}`);
    }
  }

  for (const limit of validLimits.filter((item) => item.tokenId === null)) {
    const createRes = await fetch(
      `/api/admin/token-rate-limits/user-group/${groupId}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: limit.enabled,
          token_budget: limit.tokenBudget,
          period_hours: limit.periodDays * HOURS_PER_DAY,
          cost_budget_cents: limit.costBudgetCents,
        }),
      }
    );
    if (!createRes.ok) {
      throw new Error("Failed to create token rate limit");
    }
  }

  const retainedIds = new Set(
    validLimits.flatMap((limit) =>
      limit.tokenId === null ? [] : [limit.tokenId]
    )
  );
  for (const existingLimit of existing) {
    if (retainedIds.has(existingLimit.token_id)) continue;
    const deleteRes = await fetch(
      `/api/admin/token-rate-limits/user-group/${groupId}/rate-limit/${existingLimit.token_id}`,
      { method: "DELETE" }
    );
    if (!deleteRes.ok) {
      throw new Error(
        `Failed to delete token rate limit ${existingLimit.token_id}`
      );
    }
  }
}

// ---------------------------------------------------------------------------
// Group permissions — bulk set desired permissions in a single request
// ---------------------------------------------------------------------------

async function saveGroupPermissions(
  groupId: number,
  enabledPermissions: Set<string>
): Promise<void> {
  const res = await fetch(`${USER_GROUP_URL}/${groupId}/permissions`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ permissions: Array.from(enabledPermissions) }),
  });
  if (!res.ok) {
    throw await responseError(res, "Failed to update permissions");
  }
}

async function setGroupManager(
  groupId: number,
  userId: string,
  isManager: boolean
): Promise<void> {
  const res = await fetch(`${USER_GROUP_URL}/${groupId}/manager`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, is_manager: isManager }),
  });
  if (!res.ok) {
    throw await responseError(res, "Failed to update group manager");
  }
}

export {
  renameGroup,
  createGroup,
  updateGroup,
  setGroupIncognito,
  deleteGroup,
  updateAgentGroupSharing,
  updateDocSetGroupSharing,
  saveTokenLimits,
  saveGroupPermissions,
  setGroupManager,
};
