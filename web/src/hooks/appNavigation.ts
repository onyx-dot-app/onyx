"use client";

import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import { routeWithQuery } from "@/lib/routes";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

interface UseAppRouterProps {
  chatSessionId?: string;
  agentId?: number;
  projectId?: number;
}

export function useAppRouter() {
  const router = useRouter();
  return useCallback(
    ({ chatSessionId, agentId, projectId }: UseAppRouterProps = {}) => {
      // At most one parameter is set, in this order of priority.
      const query = chatSessionId
        ? { [SEARCH_PARAM_NAMES.CHAT_ID]: chatSessionId }
        : agentId
          ? { [SEARCH_PARAM_NAMES.PERSONA_ID]: agentId }
          : projectId
            ? { [SEARCH_PARAM_NAMES.PROJECT_ID]: projectId }
            : {};

      router.push(routeWithQuery("/app", query));
    },
    [router]
  );
}

export function useAppParams() {
  const searchParams = useSearchParams();
  return useCallback((name: string) => searchParams.get(name), [searchParams]);
}
