"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { InvitedUserSnapshot } from "@/lib/types";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import type { StatusCountMap } from "@/refresh-pages/admin/UsersPage/interfaces";

type UserCountsResponse = {
  role_counts: Record<string, number>;
  status_counts: Record<string, number>;
};

type UserCounts = {
  activeCount: number | null;
  invitedCount: number | null;
  pendingCount: number | null;
  roleCounts: Record<string, number>;
  statusCounts: StatusCountMap;
  refreshCounts: () => void;
};

export default function useUserCounts(): UserCounts {
  const { data: countsData, mutate: refreshCounts } =
    useSWR<UserCountsResponse>(
      "/api/manage/users/counts",
      errorHandlingFetcher
    );

  const { data: invitedUsers } = useSWR<InvitedUserSnapshot[]>(
    "/api/manage/users/invited",
    errorHandlingFetcher
  );

  const { data: pendingUsers } = useSWR<InvitedUserSnapshot[]>(
    NEXT_PUBLIC_CLOUD_ENABLED ? "/api/tenants/users/pending" : null,
    errorHandlingFetcher
  );

  const activeCount = countsData?.status_counts?.active ?? null;
  const inactiveCount = countsData?.status_counts?.inactive ?? null;

  return {
    activeCount,
    invitedCount: invitedUsers?.length ?? null,
    pendingCount: pendingUsers?.length ?? null,
    roleCounts: countsData?.role_counts ?? {},
    statusCounts: {
      ...(activeCount !== null ? { active: activeCount } : {}),
      ...(inactiveCount !== null ? { inactive: inactiveCount } : {}),
      ...(invitedUsers ? { invited: invitedUsers.length } : {}),
      ...(pendingUsers ? { requested: pendingUsers.length } : {}),
    } satisfies StatusCountMap,
    refreshCounts,
  };
}
