import { useEffect, useRef } from "react";
import useSWR from "swr";

/** One payload per viewer. Revalidation replaces bytes, rather than caching every revision. */
export function useFilePreview<T>(
  key: string,
  load: () => Promise<T>,
  revision?: string,
  refreshKey = 0
) {
  const request = { key, revision, refreshKey };
  const previousRequest = useRef(request);
  const { data: result, mutate } = useSWR(
    key,
    async () => {
      try {
        return { revision, refreshKey, data: await load(), error: undefined };
      } catch (error) {
        return {
          revision,
          refreshKey,
          data: undefined,
          error: error instanceof Error ? error : new Error(String(error)),
        };
      }
    },
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      revalidateIfStale: revision === undefined,
    }
  );

  useEffect(() => {
    const previous = previousRequest.current;
    previousRequest.current = { key, revision, refreshKey };
    if (
      previous.key === key &&
      (previous.revision !== revision || previous.refreshKey !== refreshKey)
    ) {
      // SWR discards an older in-flight request when this revalidation starts.
      void mutate();
    }
  }, [key, revision, refreshKey, mutate]);

  const isCurrent =
    result?.revision === revision && result?.refreshKey === refreshKey;
  return {
    data: isCurrent ? result?.data : undefined,
    error: isCurrent ? result?.error : undefined,
    isLoading: !isCurrent,
  };
}
