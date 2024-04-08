import { Settings } from "@/app/admin/settings/interfaces";
import { fetchSS } from "./utilsSS";

export async function getSettingsSS(): Promise<Settings | null> {
  const response = await fetchSS("/settings");
  if (response.ok) {
    return await response.json();
  }
  return null;
}
