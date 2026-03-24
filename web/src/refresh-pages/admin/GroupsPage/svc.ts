/** API helpers for the Groups list page. */

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

export { USER_GROUP_URL, renameGroup };
