import { parseErrorDetail } from "@/lib/fetcher";
import { Settings } from "@/lib/settings/types";

// The endpoint merges only the fields sent, so a partial patch leaves the
// rest of the stored settings untouched.
export async function updateAdminSettings(
  settings: Partial<Settings>
): Promise<void> {
  const res = await fetch("/api/admin/settings", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to update settings"));
  }
}
