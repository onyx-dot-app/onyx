import { useEffect, useRef, useState } from "react";
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
}

/** One payload per viewer. Revalidation replaces bytes, rather than caching every revision. */
export function useFilePreview<T>(
  key: string,
  load: () => Promise<T>,
  { revision, refreshKey = 0, isActive = true }: FilePreviewOptions = {}
) {
  const [invalidatedError, setInvalidatedError] = useState<
    | (Error & {
        revision: string | undefined;
        refreshKey: number;
        key: string;
      })
    | undefined
  >();
  const request = { key, revision, refreshKey, isActive };
  const previousRequest = useRef<typeof request | null>(null);
  const active = useRef<boolean>(isActive);
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
      revalidateOnMount: isActive ? undefined : false,
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      revalidateIfStale: revision === undefined,
    }
  );

  useEffect(() => {
    if (error && (isAuthStatusError(error) || isNotFoundError(error))) {
      setInvalidatedError(Object.assign(error, { key }));
      // Purge accepted bytes so a later transient failure cannot restore them.
      void mutate(undefined, { revalidate: false });
    } else if (result) setInvalidatedError(undefined);
  }, [error, key, mutate, result]);

  const effectiveError =
    error ?? (invalidatedError?.key === key ? invalidatedError : undefined);
  const isCurrent =
    result?.revision === revision && result?.refreshKey === refreshKey;
  useEffect(() => {
    const previous = previousRequest.current;
    previousRequest.current = { key, revision, refreshKey, isActive };
    if (
      isActive &&
      (previous
        ? previous.key === key &&
          (previous.revision !== revision ||
            previous.refreshKey !== refreshKey ||
            (!previous.isActive &&
              (revision === undefined || error || !isCurrent)))
        : result !== undefined && !isCurrent)
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
    effectiveError?.revision === revision &&
    effectiveError?.refreshKey === refreshKey
      ? effectiveError
      : undefined;
  const isLoading: boolean = (!isCurrent || isValidating) && !currentError;

  return {
    data:
      isAuthStatusError(effectiveError) || isNotFoundError(effectiveError)
        ? undefined
        : result?.data,
    error: currentError,
    isLoading,
  };
}
