export async function deactivateUser(email: string): Promise<void> {
  const res = await fetch("/api/manage/admin/deactivate-user", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_email: email }),
  });
  if (!res.ok) {
    const detail = (await res.json()).detail;
    throw new Error(detail ?? "Failed to deactivate user");
  }
}

export async function activateUser(email: string): Promise<void> {
  const res = await fetch("/api/manage/admin/activate-user", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_email: email }),
  });
  if (!res.ok) {
    const detail = (await res.json()).detail;
    throw new Error(detail ?? "Failed to activate user");
  }
}

export async function deleteUser(email: string): Promise<void> {
  const res = await fetch("/api/manage/admin/delete-user", {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_email: email }),
  });
  if (!res.ok) {
    const detail = (await res.json()).detail;
    throw new Error(detail ?? "Failed to delete user");
  }
}
