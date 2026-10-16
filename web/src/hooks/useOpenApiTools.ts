"use client";

import { errorHandlingFetcher } from "@/lib/fetcher";
import { ToolSnapshot } from "@/lib/tools/types";
import useSWR, { type SWRConfiguration } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";

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
export default function useOpenApiTools(
  options?: Pick<SWRConfiguration, "revalidateOnMount">
) {
  const {
    data: openApiTools,
    error,
    isLoading: isOpenApiLoading,
    isValidating,
    mutate: mutateOpenApiTools,
  } = useSWR<ToolSnapshot[]>(
    SWR_KEYS.openApiTools,
    errorHandlingFetcher,
    options
  );

  return {
    openApiTools: openApiTools ?? null,
    isLoading: isOpenApiLoading,
    isValidating,
    error,
    mutateOpenApiTools,
  };
}
