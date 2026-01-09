"use client";

import useSWR from "swr";
import { CCPairBasicInfo } from "@/lib/types";
import { errorHandlingFetcher } from "@/lib/fetcher";

/**
 * Hook for fetching connector-credential pairs (CC Pairs).
 *
 * Retrieves all connector-credential pairs configured in the system. CC Pairs
 * represent connections between data sources (connectors) and their authentication
 * credentials, used for indexing content from various sources like Confluence,
 * Slack, Google Drive, etc. Uses SWR for caching and automatic revalidation.
 *
 * @returns Object containing:
 *   - ccPairs: Array of CCPairBasicInfo objects
 *   - isLoading: Boolean indicating if data is being fetched
 *   - error: Error object if the fetch failed
 *   - refetch: Function to manually reload CC pairs
 *
 * @example
 * ```tsx
 * // Display list of connected data sources
 * const ConnectorList = () => {
 *   const { ccPairs, isLoading, error } = useCCPairs();
 *
 *   if (isLoading) return <Spinner />;
 *   if (error) return <Error message="Failed to load connectors" />;
 *
 *   return (
 *     <ul>
 *       {ccPairs.map(pair => (
 *         <li key={pair.id}>
 *           {pair.name} - {pair.source}
 *         </li>
 *       ))}
 *     </ul>
 *   );
 * };
 * ```
 *
 * @example
 * ```tsx
 * // Filter connectors by source type
 * const SlackConnectors = () => {
 *   const { ccPairs } = useCCPairs();
 *
 *   const slackPairs = ccPairs.filter(pair => pair.source === 'slack');
 *
 *   return <ConnectorGrid connectors={slackPairs} />;
 * };
 * ```
 *
 * @example
 * ```tsx
 * // Refresh list after connecting a new source
 * const ConnectSourceButton = () => {
 *   const { refetch } = useCCPairs();
 *
 *   const handleConnect = async () => {
 *     await connectNewSource();
 *     refetch(); // Refresh the list
 *   };
 *
 *   return <Button onClick={handleConnect}>Connect Source</Button>;
 * };
 * ```
 */
export default function useCCPairs() {
  const { data, error, isLoading, mutate } = useSWR<CCPairBasicInfo[]>(
    "/api/manage/connector-status",
    errorHandlingFetcher
  );

  return {
    ccPairs: data ?? [],
    isLoading,
    error,
    refetch: mutate,
  };
}
