import { UserRole } from "@/lib/types";

async function parseErrorDetail(
  res: Response,
  fallback: string
): Promise<string> {
  try {
    const body = await res.json();
    return body?.detail ?? fallback;
  } catch {
    return fallback;
  }
}

export async function deactivateUser(email: string): Promise<void> {
  const res = await fetch("/api/manage/admin/deactivate-user", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_email: email }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to deactivate user"));
  }
}

export async function activateUser(email: string): Promise<void> {
  const res = await fetch("/api/manage/admin/activate-user", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_email: email }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to activate user"));
  }
}

export async function deleteUser(email: string): Promise<void> {
  const res = await fetch("/api/manage/admin/delete-user", {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_email: email }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to delete user"));
  }
}

export async function setUserRole(
  email: string,
  newRole: UserRole
): Promise<void> {
  const res = await fetch("/api/manage/set-user-role", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_email: email, new_role: newRole }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to update user role"));
  }
}

export async function addUserToGroup(
  groupId: number,
  userId: string
): Promise<void> {
  const res = await fetch(`/api/manage/admin/user-group/${groupId}/add-users`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_ids: [userId] }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to add user to group"));
  }
}

export async function removeUserFromGroup(
  groupId: number,
  currentUserIds: string[],
  userIdToRemove: string,
  ccPairIds: number[]
): Promise<void> {
  const res = await fetch(`/api/manage/admin/user-group/${groupId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_ids: currentUserIds.filter((id) => id !== userIdToRemove),
      cc_pair_ids: ccPairIds,
    }),
  });
  if (!res.ok) {
    throw new Error(
      await parseErrorDetail(res, "Failed to remove user from group")
    );
  }
}

export async function cancelInvite(email: string): Promise<void> {
  const res = await fetch("/api/manage/admin/remove-invited-user", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_email: email }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to cancel invite"));
  }
}

export async function approveRequest(email: string): Promise<void> {
  const res = await fetch("/api/tenants/users/invite/approve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to approve request"));
  }
}

export async function inviteUsers(emails: string[]): Promise<void> {
  const res = await fetch("/api/manage/admin/users", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ emails }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to invite users"));
  }
}

export async function downloadUsersCsv(): Promise<void> {
  const res = await fetch("/api/manage/users/download");
  if (!res.ok) {
    const detail = (await res.json()).detail;
    throw new Error(detail ?? "Failed to download users CSV");
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "onyx_users.csv";
  a.click();
  URL.revokeObjectURL(url);
}
