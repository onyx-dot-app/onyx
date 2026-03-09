"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { UserRole } from "@/lib/types";
import type { PaginatedUsersResponse } from "@/refresh-pages/admin/UsersPage/interfaces";

interface UseAdminUsersParams {
  pageIndex: number;
  pageSize: number;
  searchTerm?: string;
  roles?: UserRole[];
  isActive?: boolean | undefined;
}

export default function useAdminUsers({
  pageIndex,
  pageSize,
  searchTerm,
  roles,
  isActive,
}: UseAdminUsersParams) {
  const queryParams = new URLSearchParams({
    page_num: String(pageIndex),
    page_size: String(pageSize),
    ...(searchTerm && { q: searchTerm }),
    ...(isActive === true && { is_active: "true" }),
    ...(isActive === false && { is_active: "false" }),
  });
  for (const role of roles ?? []) {
    queryParams.append("roles", role);
  }

  const { data, isLoading, error, mutate } = useSWR<PaginatedUsersResponse>(
    `/api/manage/users/accepted?${queryParams.toString()}`,
    errorHandlingFetcher
  );

  return {
    users: data?.items ?? [],
    totalItems: data?.total_items ?? 0,
    isLoading,
    error,
    refresh: mutate,
  };
}
