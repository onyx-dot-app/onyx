"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { SkillInstallationPolicy } from "@/lib/skills/types";
import { setGroupPluginInstallationPolicy } from "@/lib/groupPlugins/api";
import type { UserGroupPlugin } from "@/lib/groupPlugins/types";

export function useUserGroupPlugins(groupId: number) {
  const { data, error, isLoading, mutate } = useSWR<UserGroupPlugin[]>(
    SWR_KEYS.userGroupPlugins(groupId),
    errorHandlingFetcher
  );

  async function setPolicy(
    pluginId: string,
    installationPolicy: SkillInstallationPolicy | null
  ): Promise<void> {
    const next = await setGroupPluginInstallationPolicy(
      groupId,
      pluginId,
      installationPolicy
    );
    await mutate(next, { revalidate: false });
  }

  return { data, error, isLoading, refresh: mutate, setPolicy };
}
