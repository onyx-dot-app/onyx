"use client";

import useSWR from "swr";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";

/**
 * Hook to fetch all available tools from the backend.
 *
 * This hook fetches the complete list of tools that can be used with agents,
 * including built-in tools (SearchTool, ImageGenerationTool, WebSearchTool, PythonTool)
 * and any dynamically configured tools (MCP servers, OpenAPI tools).
 *
 * @example
 * ```tsx
 * const { tools, isLoading, error, refresh } = useAvailableTools();
 *
 * if (isLoading) return <Loading />;
 * if (error) return <Error />;
 *
 * const imageGenTool = tools.find(t => t.in_code_tool_id === "ImageGenerationTool");
 * const isImageGenAvailable = !!imageGenTool;
 * ```
 */
export function useAvailableTools() {
  const { data, error, mutate } = useSWR<ToolSnapshot[]>(
    "/api/tool",
    errorHandlingFetcher,
    {
      revalidateOnFocus: true,
    }
  );

  return {
    tools: data ?? [],
    isLoading: !error && !data,
    error,
    refresh: mutate,
  };
}
