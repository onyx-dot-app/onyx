"use client";

import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { useCallback } from "react";

interface UseAppRouterProps {
  chatSessionId?: string;
  agentId?: number;
  projectId?: number;
  assistantId?: number;
}

export function useAppRouter() {
  const router = useRouter();
  return useCallback(
    ({
      chatSessionId,
      agentId,
      projectId,
      assistantId,
    }: UseAppRouterProps = {}) => {
      const finalParams = [];

      if (chatSessionId)
        finalParams.push(`${SEARCH_PARAM_NAMES.CHAT_ID}=${chatSessionId}`);
      else if (agentId)
        finalParams.push(`${SEARCH_PARAM_NAMES.PERSONA_ID}=${agentId}`);
      else if (projectId)
        finalParams.push(`${SEARCH_PARAM_NAMES.PROJECT_ID}=${projectId}`);
      else if (assistantId)
        finalParams.push(`${SEARCH_PARAM_NAMES.PERSONA_ID}=${assistantId}`);

      const finalString = finalParams.join("&");
      const finalUrl = `/chat?${finalString}`;

      router.push(finalUrl as Route);
    },
    [router]
  );
}

export function useAppParams() {
  const searchParams = useSearchParams();
  return useCallback((name: string) => searchParams.get(name), [searchParams]);
}
