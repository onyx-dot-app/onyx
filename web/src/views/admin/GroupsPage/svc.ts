/** API helpers for the Groups pages. */

import type { ScopedMutator } from "swr";
import type { ErrorResponseBody } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { UserGroup } from "@/lib/types";

const USER_GROUP_URL = SWR_KEYS.adminUserGroups;

/**
 * Refresh both group-list caches. These pages read the include_default key, but the users
 * and connector pages read the plain one, so a rename, membership edit or delete has to
 * reach both or they keep serving a stale name or a group that no longer exists.
 */
async function refreshGroupLists(mutate: ScopedMutator): Promise<void> {
  await Promise.all([
    mutate(SWR_KEYS.adminUserGroups),
    mutate(SWR_KEYS.adminUserGroupsWithDefault),
  ]);
}

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
  const group: UserGroup = await res.json();
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
    const detail: ErrorResponseBody | null = await res.json().catch(() => null);
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
  refreshGroupLists,
  renameGroup,
  createGroup,
  updateGroup,
  setGroupIncognito,
  deleteGroup,
  updateAgentGroupSharing,
  updateDocSetGroupSharing,
  saveGroupPermissions,
  setGroupManager,
};
