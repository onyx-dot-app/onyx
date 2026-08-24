"use client";

import { useMemo } from "react";
import useSWR from "swr";
import { Project, ProjectSearchMatch } from "@/lib/projects/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { UNNAMED_CHAT } from "@/lib/constants";
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

/**
 * Projects narrowed by one query, matching project names and chat names.
 *
 * A project is listed when its own name matches, or when any of its chats does.
 * A chat hit narrows the project to those chats and marks it, so the row opens
 * and shows the reason it is listed. A name hit keeps the project whole.
 *
 * Chats match on the label the sidebar renders, `name || UNNAMED_CHAT`, so what
 * you search is what you see. Everything is already in memory — `chat_sessions`
 * arrives with the project list — so there is nothing to debounce.
 */
export function useProjectSearch(query: string): ProjectSearchMatch[] {
  const { projects } = useProjects();

  return useMemo(() => {
    const term = query.trim().toLowerCase();

    if (!term)
      return projects.map((project) => ({
        project,
        chatSessions: project.chat_sessions,
        chatMatched: false,
      }));

    return projects.flatMap((project) => {
      const matchedChats = project.chat_sessions.filter((chatSession) =>
        (chatSession.name || UNNAMED_CHAT).toLowerCase().includes(term)
      );
      const nameMatched = project.name.toLowerCase().includes(term);

      if (!nameMatched && matchedChats.length === 0) return [];

      // A hit on the project's own name keeps it whole — the project is what
      // matched, so hiding the chats it holds would answer a different
      // question. Only a chat-only hit narrows, and only that opens the row.
      return [
        {
          project,
          chatSessions: nameMatched ? project.chat_sessions : matchedChats,
          chatMatched: !nameMatched && matchedChats.length > 0,
        },
      ];
    });
  }, [projects, query]);
}
