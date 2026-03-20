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
): Promise<void> {
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
}

export { USER_GROUP_URL, renameGroup, createGroup };
