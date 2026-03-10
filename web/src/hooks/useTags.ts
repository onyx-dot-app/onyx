import useSWR from "swr";
import { Tag } from "@/lib/types";
import { errorHandlingFetcher } from "@/lib/fetcher";

interface TagsResponse {
  tags: Tag[];
}

/**
 * Fetches the set of valid tags from the server.
 *
 * Tags are deduplicated for 60 s and not re-fetched on window focus.
 *
 * @returns tags - The array of available {@link Tag} objects (empty while loading).
 * @returns isLoading - `true` until the first successful fetch or an error.
 * @returns error - The error object if the request failed.
 * @returns refresh - SWR mutate function to manually re-fetch.
 */
export default function useTags() {
  const { data, error, mutate } = useSWR<TagsResponse>(
    "/api/query/valid-tags",
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 60000,
    }
  );

  return {
    tags: data?.tags ?? [],
    isLoading: !error && !data,
    error,
    refresh: mutate,
  };
}
