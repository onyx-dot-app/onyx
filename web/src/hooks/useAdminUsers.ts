"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { UserRow } from "@/refresh-pages/admin/UsersPage/interfaces";

export default function useAdminUsers() {
  const { data, isLoading, error, mutate } = useSWR<UserRow[]>(
    "/api/manage/users/accepted/all",
    errorHandlingFetcher
  );

  return {
    users: data ?? [],
    isLoading,
    error,
    refresh: mutate,
  };
}
