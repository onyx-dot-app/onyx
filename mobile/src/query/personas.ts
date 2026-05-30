// Personas (agents) query. GET /api/persona returns the list of personas/agents.
import { useQuery } from "@tanstack/react-query";
import { errorHandlingFetcher } from "@/lib/api";
import type { MinimalAgent } from "@/lib/types";
import { queryKeys } from "./keys";
import { clientConfig } from "./client";

export function usePersonas() {
  return useQuery({
    queryKey: [queryKeys.personas],
    queryFn: () =>
      errorHandlingFetcher<MinimalAgent[]>(queryKeys.personas, clientConfig),
  });
}
