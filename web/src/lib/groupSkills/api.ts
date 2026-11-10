import { errorHandlingFetchWith, errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  userGroupSkillsSchema,
  type GroupInstallationPolicy,
  type GroupSkillTarget,
} from "@/lib/groupSkills/types";

const strict = { strict: true };

export async function getUserGroupSkills(groupId: number) {
  const data = await errorHandlingFetcher<unknown>(
    SWR_KEYS.userGroupSkills(groupId)
  );
  return userGroupSkillsSchema.validateSync(data, strict);
}

/** null removes the group setting, so the group inherits the company one. */
export async function setGroupInstallationPolicy({
  groupId,
  target,
  installationPolicy,
}: {
  groupId: number;
  target: GroupSkillTarget;
  installationPolicy: GroupInstallationPolicy | null;
}) {
  const collection = target.kind === "skill" ? "skills" : "marketplaces";
  const data = await errorHandlingFetchWith<unknown>(
    `/api/manage/admin/user-group/${groupId}/${collection}/${encodeURIComponent(
      target.id
    )}/installation-policy`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ installation_policy: installationPolicy }),
    }
  );
  return userGroupSkillsSchema.validateSync(data, strict);
}
