import { useEffect, useEffectEvent, useLayoutEffect, useRef } from "react";
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
  const lifecycle = useRef<{
    identity: string;
    isActive: boolean;
    error?: FilePreviewError;
  }>({ identity, isActive });
  const pendingValidation = useRef<{ identity: string } | null>(null);
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
        if (
          !lifecycle.current.isActive ||
          lifecycle.current.identity !== error.identity
        )
          return;
        skipRetryOnAuthError(
          error.failure,
          key,
          config,
          (retryOptions) => {
            if (
              lifecycle.current.isActive &&
              lifecycle.current.identity === error.identity &&
              lifecycle.current.error === error
            )
              revalidate(retryOptions);
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

  useLayoutEffect(() => {
    lifecycle.current = { identity, isActive, error };
    return () => {
      lifecycle.current.isActive = false;
    };
  }, [identity, isActive, error]);

  const validate = useEffectEvent(() => {
    const reusable =
      revision !== undefined &&
      result?.identity === identity &&
      !result.error &&
      !error;
    if (reusable || pendingValidation.current?.identity === identity) return;
    // SWR mutate forces revalidation; reuse StrictMode's replay of this request.
    const pending = { identity };
    pendingValidation.current = pending;
    void mutate()
      .catch(() => undefined)
      .finally(() => {
        if (pendingValidation.current === pending)
          pendingValidation.current = null;
      });
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
