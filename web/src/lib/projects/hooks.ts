"use client";

import { useMemo } from "react";
import useSWR from "swr";
import { Project } from "@/lib/projects/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import useAppFocus from "@/hooks/useAppFocus";

export function useProjects() {
  const { data, error, mutate } = useSWR<Project[]>(
    SWR_KEYS.userProjects,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
      dedupingInterval: 30000,
    }
  );

  return {
    projects: data ?? [],
    isLoading: !error && !data,
    error,
    refreshProjects: mutate,
  };
}

/**
 * The project the user is currently inside: either the open project page, or
 * the project that owns the open chat.
 *
 * A chat's project is found by searching for the project that lists it. The URL
 * cannot answer this on its own — `projectId` is dropped once a chat opens (see
 * `PARAMS_TO_SKIP` in `app/app/services/lib.tsx`), so a chat URL carries no
 * project context.
 */
export function useActiveProject(): Project | null {
  const appFocus = useAppFocus();
  const { projects } = useProjects();

  return useMemo(() => {
    const id = appFocus.getId();
    if (!id) return null;

    if (appFocus.isProject()) {
      return projects.find((project) => String(project.id) === id) ?? null;
    }
    if (appFocus.isChat()) {
      return (
        projects.find((project) =>
          project.chat_sessions.some((session) => session.id === id)
        ) ?? null
      );
    }
    return null;
  }, [appFocus, projects]);
}
