// Global tool registry query. GET /tool returns every tool defined in the
// backend (built-ins + custom/MCP/OpenAPI). Mirrors web's useAvailableTools:
// a tool is "available" for the current chat iff its id is in this set.
import { useQuery } from "@tanstack/react-query";
import { errorHandlingFetcher } from "@/lib/api";
import type { ToolSnapshot } from "@/lib/types/tools";
import { queryKeys } from "./keys";
import { clientConfig } from "./client";

export function useTools() {
  return useQuery({
    queryKey: [queryKeys.tools],
    queryFn: () =>
      errorHandlingFetcher<ToolSnapshot[]>(queryKeys.tools, clientConfig),
    staleTime: 60_000,
  });
}
