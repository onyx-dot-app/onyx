import { useEffect, useRef } from "react";
import useSWR from "swr";
import {
  isAuthStatusError,
  isNotFoundError,
  skipRetryOnAuthError,
} from "@/lib/fetcher";

interface FilePreviewOptions {
  revision?: string;
  refreshKey?: number;
  isActive?: boolean;
  onRefreshingChange?: (refreshing: boolean) => void;
}

/** One payload per viewer. Revalidation replaces bytes, rather than caching every revision. */
export function useFilePreview<T>(
  key: string,
  load: () => Promise<T>,
  {
    revision,
    refreshKey = 0,
    isActive = true,
    onRefreshingChange,
  }: FilePreviewOptions = {}
) {
  const request = { key, revision, refreshKey, isActive };
  const previousRequest = useRef(request);
  const active = useRef(isActive);
  active.current = isActive;
  const {
    data: result,
    error,
    mutate,
    isValidating,
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
      // Structural comparison cannot distinguish different Blob contents.
      compare: (previous, next) =>
        previous?.revision === next?.revision &&
        previous?.refreshKey === next?.refreshKey &&
        Object.is(previous?.data, next?.data),
      onErrorRetry: (error, key, config, revalidate, options) => {
        if (!active.current) return;
        skipRetryOnAuthError(
          error,
          key,
          config,
          (retryOptions) => {
            if (active.current) revalidate(retryOptions);
          },
          options
        );
      },
      revalidateOnMount: isActive,
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      revalidateIfStale: revision === undefined,
    }
  );

  const isCurrent =
    result?.revision === revision && result?.refreshKey === refreshKey;
  useEffect(() => {
    const previous = previousRequest.current;
    previousRequest.current = { key, revision, refreshKey, isActive };
    if (
      isActive &&
      previous.key === key &&
      (previous.revision !== revision ||
        previous.refreshKey !== refreshKey ||
        (!previous.isActive && (revision === undefined || error || !isCurrent)))
    ) {
      // SWR discards an older in-flight request when this revalidation starts.
      void mutate().catch(() => undefined);
    }
  }, [
    key,
    revision,
    refreshKey,
    isActive,
    isValidating,
    error,
    isCurrent,
    mutate,
  ]);

  const currentError: Error | undefined =
    error?.revision === revision && error?.refreshKey === refreshKey
      ? error
      : undefined;
  const isLoading = (!isCurrent || isValidating) && !currentError;
  useEffect(() => {
    onRefreshingChange?.(isActive && isLoading);
    return () => onRefreshingChange?.(false);
  }, [isActive, isLoading, onRefreshingChange]);

  return {
    data:
      isAuthStatusError(error) || isNotFoundError(error)
        ? undefined
        : result?.data,
    error: currentError,
    isLoading,
  };
}
