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
  const {
    data: result,
    error,
    mutate,
  } = useSWR<
    { revision: string | undefined; refreshKey: number; data: T },
    Error & { revision: string | undefined; refreshKey: number }
  >(
    key,
    async () => {
      try {
        return { revision, refreshKey, data: await load() };
      } catch (error) {
        throw Object.assign(
          error instanceof Error ? error : new Error(String(error)),
          { revision, refreshKey }
        );
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
  const currentError: Error | undefined =
    error?.revision === revision && error?.refreshKey === refreshKey
      ? error
      : undefined;
  return {
    data: isCurrent ? result?.data : undefined,
    error: currentError,
    isLoading: !isCurrent && !currentError,
  };
}
