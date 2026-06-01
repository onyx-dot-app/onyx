// Mirrors web's useAvailableTools: a tool is "available" iff its id is in this set.
import type { ToolSnapshot } from "@/lib/types/tools";
import { queryKeys } from "./keys";
import { useSimpleQuery } from "./client";

export function useTools() {
  return useSimpleQuery<ToolSnapshot[]>(queryKeys.tools, { staleTime: 60_000 });
}
