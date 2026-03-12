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
