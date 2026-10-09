import { useEffect, useEffectEvent, useRef } from "react";
import useSWR from "swr";
import type { FilePreviewResult } from "@/lib/build/types";
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

class FilePreviewError extends Error {
  constructor(
    readonly identity: string,
    readonly failure: Error
  ) {
    super(failure.message, { cause: failure });
  }
}

/** One payload per viewer. Revalidation replaces bytes, rather than caching every revision. */
export function useFilePreview<T>(
  key: string,
  load: () => Promise<T>,
  { revision, refreshKey = 0, isActive = true }: FilePreviewOptions = {}
) {
  const identity = JSON.stringify([key, revision, refreshKey]);
  const active = useRef(isActive);
  active.current = isActive;
  const {
    data: result,
    error,
    mutate,
    isValidating,
  } = useSWR<FilePreviewResult<T>, FilePreviewError>(
    key,
    async () => {
      try {
        return { identity, data: await load() };
      } catch (failure) {
        const error =
          failure instanceof Error ? failure : new Error(String(failure));
        if (isAuthStatusError(error) || isNotFoundError(error)) {
          // A cached failure replaces bytes, so later failures cannot restore them.
          return { identity, error };
        }
        throw new FilePreviewError(identity, error);
      }
    },
    {
      // Structural comparison cannot distinguish different Blob contents.
      compare: (previous, next) =>
        previous?.identity === next?.identity &&
        Object.is(previous?.data, next?.data) &&
        previous?.error === next?.error,
      onErrorRetry: (error, key, config, revalidate, options) => {
        if (!active.current) return;
        skipRetryOnAuthError(
          error.failure,
          key,
          config,
          (retryOptions) => {
            if (active.current) revalidate(retryOptions);
          },
          options
        );
      },
      revalidateOnMount: false,
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      revalidateIfStale: false,
    }
  );

  const validate = useEffectEvent(() => {
    const reusable =
      revision !== undefined &&
      result?.identity === identity &&
      !result.error &&
      !error;
    if (!reusable) void mutate().catch(() => undefined);
  });
  useEffect(() => {
    if (isActive) validate();
  }, [identity, isActive]);

  const currentError: Error | undefined =
    error?.identity === identity
      ? error.failure
      : result?.identity === identity
        ? result.error
        : undefined;
  const isLoading =
    (result?.identity !== identity || isValidating) && !currentError;

  return {
    data: result?.data,
    error: currentError,
    isLoading,
  };
}
