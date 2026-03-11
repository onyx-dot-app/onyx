"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { InvitedUserSnapshot } from "@/lib/types";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";

type PaginatedCountResponse = {
  total_items: number;
};

type UserCounts = {
  activeCount: number | null;
  invitedCount: number | null;
  pendingCount: number | null;
};

export default function useUserCounts(): UserCounts {
  // Active user count — lightweight fetch (page_size=1 to minimize payload)
  const { data: activeData } = useSWR<PaginatedCountResponse>(
    "/api/manage/users/accepted?page_num=0&page_size=1",
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

  return {
    activeCount: activeData?.total_items ?? null,
    invitedCount: invitedUsers?.length ?? null,
    pendingCount: pendingUsers?.length ?? null,
  };
}
