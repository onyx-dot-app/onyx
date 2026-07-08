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

/** Set (true/false) or clear (null) the Craft override for one or more users. */
export async function setUsersCraftAccess(
  emails: string[],
  craftEnabled: boolean | null
): Promise<void> {
  const res = await fetch("/api/manage/admin/users/craft-enabled", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_emails: emails, craft_enabled: craftEnabled }),
  });
  if (!res.ok) {
    throw new Error(
      await parseErrorDetail(res, "Failed to update Craft access")
    );
  }
}
