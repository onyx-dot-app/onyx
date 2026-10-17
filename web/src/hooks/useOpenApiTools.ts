"use client";

import { errorHandlingFetcher } from "@/lib/fetcher";
import { ToolSnapshot } from "@/lib/tools/types";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useCallback } from "react";

/**
 * Fetches OpenAPI tools configuration.
 *
 * OpenAPI tools provide custom actions and integrations to agents through
 * OpenAPI specifications.
 *
 * @returns Object containing:
 *   - openApiTools: ToolSnapshot[] data or null if not loaded
 *   - isLoading: Boolean indicating if data is being fetched
 *   - error: Any error that occurred during fetch
 *   - mutateOpenApiTools: Function to manually revalidate the data
 *
 * @example
 * const { openApiTools, isLoading } = useOpenApiTools();
 * if (isLoading) return <Spinner />;
 * return <OpenApiToolsList tools={openApiTools} />;
 */
export default function useOpenApiTools() {
  const {
    data: openApiTools,
    error,
    isLoading: isOpenApiLoading,
    mutate: mutateOpenApiTools,
  } = useSWR<ToolSnapshot[]>(SWR_KEYS.openApiTools, errorHandlingFetcher);
  const refreshOpenApiTools = useCallback(
    () =>
      mutateOpenApiTools(
        errorHandlingFetcher<ToolSnapshot[]>(SWR_KEYS.openApiTools),
        { revalidate: false }
      ),
    [mutateOpenApiTools]
  );

  return {
    openApiTools: openApiTools ?? null,
    isLoading: isOpenApiLoading,
    error,
    mutateOpenApiTools,
    refreshOpenApiTools,
  };
}
