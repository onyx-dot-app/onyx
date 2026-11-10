"use client";

import useSWR, { useSWRConfig } from "swr";
import { FetchError, isAuthStatusError, isNotFoundError } from "@/lib/fetcher";
import {
  getUserGroupSkills,
  setGroupInstallationPolicy,
} from "@/lib/groupSkills/api";
import type {
  GroupInstallationPolicy,
  GroupSkillTarget,
  UserGroupSkills,
} from "@/lib/groupSkills/types";
import { SWR_KEYS } from "@/lib/swr-keys";

type GroupSkillsRead =
  | { kind: "available"; value: UserGroupSkills }
  | { kind: "denied"; error: FetchError };

async function readGroupSkills(groupId: number): Promise<GroupSkillsRead> {
  try {
    return { kind: "available", value: await getUserGroupSkills(groupId) };
  } catch (error) {
    if (
      error instanceof FetchError &&
      (isAuthStatusError(error) || isNotFoundError(error))
    ) {
      return { kind: "denied", error };
    }
    throw error;
  }
}

/** Pass null to skip the request, for example when the caller cannot read Skills. */
export function useUserGroupSkills(groupId: number | null) {
  const { mutate } = useSWRConfig();
  const { data, error, isLoading } = useSWR<GroupSkillsRead, Error>(
    groupId === null ? null : SWR_KEYS.userGroupSkills(groupId),
    groupId === null ? null : () => readGroupSkills(groupId)
  );

  async function setPolicy(
    target: GroupSkillTarget,
    installationPolicy: GroupInstallationPolicy | null
  ) {
    if (groupId === null) return;
    const next = await setGroupInstallationPolicy({
      groupId,
      target,
      installationPolicy,
    });
    // Keep a later denial and bind this result to the group that started the PUT.
    await mutate<GroupSkillsRead>(
      SWR_KEYS.userGroupSkills(groupId),
      (current) =>
        current?.kind === "denied"
          ? current
          : { kind: "available", value: next },
      { revalidate: false }
    );
  }

  return {
    data: data?.kind === "available" ? data.value : undefined,
    error: error ?? (data?.kind === "denied" ? data.error : undefined),
    isLoading,
    setPolicy,
  };
}
