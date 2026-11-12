import { errorHandlingFetchWith } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { SkillInstallationPolicy } from "@/lib/skills/types";
import type { UserGroupPlugin } from "@/lib/groupPlugins/types";

/** Set the group's setting of a plugin. Null removes it, so the group uses the
 * organization setting. A private plugin that the group does not have yet is
 * shared with the group. Returns the group's new plugin list. */
export function setGroupPluginInstallationPolicy(
  groupId: number,
  pluginId: string,
  installationPolicy: SkillInstallationPolicy | null
): Promise<UserGroupPlugin[]> {
  return errorHandlingFetchWith<UserGroupPlugin[]>(
    `${SWR_KEYS.userGroupPlugins(groupId)}/${encodeURIComponent(pluginId)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ installation_policy: installationPolicy }),
    }
  );
}
