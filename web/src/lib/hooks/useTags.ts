import useSWR from "swr";
import { Tag } from "@/lib/types";
import { errorHandlingFetcher } from "@/lib/fetcher";

interface TagsResponse {
  tags: Tag[];
}

export function useTags() {
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
