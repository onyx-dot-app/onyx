import {
  useEffect,
  useEffectEvent,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useCallback,
} from "react";
import useSWR, { unstable_serialize, useSWRConfig, type Key } from "swr";
import {
  isAuthStatusError,
  isNotFoundError,
  skipRetryOnAuthError,
} from "@/lib/fetcher";

import {
  useBuildSessionStore,
  type BuildSessionData,
} from "@/app/craft/hooks/useBuildSessionStore";
import { useUser } from "@/providers/UserProvider";
import { saveOutputPanelPreferences } from "@/app/craft/services/outputPanelPreferences";
import type {
  ApiWebappInfoResponse,
  OutputCard,
} from "@/app/craft/types/streamingTypes";
import {
  fetchWebappInfo,
  fetchOutputCards,
  markOutputViewed,
  markOutputsViewed,
} from "@/app/craft/services/apiServices";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  RegisteredWebapp,
  AppDiscoveryState,
  FilePreviewResult,
} from "@/lib/build/types";

const EMPTY_OUTPUT_CARDS: readonly OutputCard[] = [];

/** The persisted turn index is independent of sandbox and preview lifecycles. */
export function useOutputCards(sessionId: string | null) {
  const { user } = useUser();
  const userId = user?.id;
  const { mutate } = useSWRConfig();
  const { data, error } = useSWR<OutputCard[], Error>(
    sessionId && user?.id
      ? [SWR_KEYS.buildSessionOutputCards(sessionId), user.id]
      : null,
    sessionId ? () => fetchOutputCards(sessionId) : null,
    { onErrorRetry: skipRetryOnAuthError }
  );
  const saveViewed = useCallback(
    async (cards: readonly OutputCard[]) => {
      const pending = cards.filter(
        (card) => !card.deleted && (card.viewed_revision ?? 0) < card.revision
      );
      if (!sessionId || !userId || pending.length === 0) return;
      const first = pending[0];
      const acknowledged =
        first && pending.length === 1
          ? [await markOutputViewed(sessionId, first)]
          : await markOutputsViewed(sessionId, pending);
      const revisions = new Map(
        acknowledged.map((card) => [card.id, card.viewed_revision ?? 0])
      );
      // Update the captured session key; late acknowledgements cannot replace newer output revisions.
      await mutate<OutputCard[]>(
        [SWR_KEYS.buildSessionOutputCards(sessionId), userId],
        (current) =>
          current?.map((item) => {
            const viewed = revisions.get(item.id);
            return viewed === undefined
              ? item
              : {
                  ...item,
                  viewed_revision: Math.max(item.viewed_revision ?? 0, viewed),
                };
          }),
        { revalidate: true }
      );
    },
    [sessionId, userId, mutate]
  );
  const markViewed = useCallback(
    async (card: OutputCard) => {
      try {
        await saveViewed([card]);
      } catch {
        // Opening remains usable on failure; retain the unread marker for retry.
      }
    },
    [saveViewed]
  );
  const markAllViewed = useCallback(
    () => saveViewed(data ?? []),
    [saveViewed, data]
  );

  return {
    cards:
      isAuthStatusError(error) || isNotFoundError(error)
        ? EMPTY_OUTPUT_CARDS
        : (data ?? EMPTY_OUTPUT_CARDS),
    markViewed,
    markAllViewed,
  };
}

/** Saves panel UI preferences independently of workspace layout. */
export function useOutputPanelPersistence() {
  useEffect(() => {
    for (const [id, session] of useBuildSessionStore.getState().sessions)
      saveOutputPanelPreferences(id, session);
    return useBuildSessionStore.subscribe((state, previous) => {
      for (const [id, session] of state.sessions) {
        const before = previous.sessions.get(id);
        if (
          before?.outputPanelMode !== session.outputPanelMode ||
          before?.outputPanelInitialized !== session.outputPanelInitialized ||
          before?.panelTabs !== session.panelTabs ||
          before?.activePanelTabId !== session.activePanelTabId ||
          before?.panelTabHistory !== session.panelTabHistory ||
          before?.mediumPanelProportion !== session.mediumPanelProportion ||
          before?.filesTabState !== session.filesTabState
        )
          saveOutputPanelPreferences(id, session);
      }
    });
  }, []);
}

interface FilePreviewOptions {
  revision?: string;
  refreshKey?: number;
  isActive?: boolean;
  onRefreshingChange?: (refreshing: boolean) => void;
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
  {
    revision,
    refreshKey = 0,
    isActive = true,
    onRefreshingChange,
  }: FilePreviewOptions = {}
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

  useOutputRefreshStatus(isActive && isLoading, onRefreshingChange);

  return {
    data: result?.data,
    error: currentError,
    isLoading,
  };
}
const WORKSPACE_LISTING_FRESHNESS_MS = 30_000;

interface WorkspaceListingOptions<T> {
  isActive: boolean;
  isVisible?: boolean;
  refreshGeneration: number;
  fallbackData?: T;
  merge?: (previous: T | undefined, next: T) => T;
}

interface CachedWorkspaceListing<T> {
  data: T | undefined;
  error?: Error;
  readAt: number;
  refreshGeneration: number;
}

/** Successful listings stay fresh briefly; explicit changes always bypass freshness. */
export function useWorkspaceListing<T>(
  key: Key,
  load: (signal: AbortSignal) => Promise<T>,
  {
    isActive,
    isVisible = isActive,
    refreshGeneration,
    fallbackData,
    merge,
  }: WorkspaceListingOptions<T>
) {
  const request = useRef<AbortController | null>(null);
  const [requestPending, setRequestPending] = useState(false);
  const {
    data: result,
    error,
    isValidating,
    mutate,
  } = useSWR<CachedWorkspaceListing<T>, Error>(
    key,
    async (): Promise<CachedWorkspaceListing<T>> => {
      request.current?.abort();
      const controller = new AbortController();
      request.current = controller;
      setRequestPending(true);
      try {
        const data = await load(controller.signal);
        controller.signal.throwIfAborted();
        return {
          data: merge ? merge(result?.data, data) : data,
          readAt: Date.now(),
          refreshGeneration,
        };
      } catch (error) {
        controller.signal.throwIfAborted();
        if (
          error instanceof Error &&
          (isAuthStatusError(error) || isNotFoundError(error))
        ) {
          // A terminal result replaces accepted rows and persisted fallback together.
          return { data: undefined, error, readAt: 0, refreshGeneration };
        }
        throw error;
      } finally {
        if (request.current === controller) {
          request.current = null;
          setRequestPending(false);
        }
      }
    },
    {
      revalidateOnMount: false,
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      shouldRetryOnError: false,
      fallbackData:
        fallbackData === undefined
          ? undefined
          : { data: fallbackData, readAt: 0, refreshGeneration: -1 },
      isPaused: () => !isActive,
    }
  );
  const cacheKey = unstable_serialize(key);
  const effectiveError =
    error?.name === "AbortError" ? result?.error : (error ?? result?.error);
  const validate = useEffectEvent(() => {
    if (request.current) return;
    const fresh =
      result !== undefined &&
      !effectiveError &&
      result.refreshGeneration === refreshGeneration &&
      Date.now() - result.readAt < WORKSPACE_LISTING_FRESHNESS_MS;
    if (!fresh) void mutate().catch(() => undefined);
  });
  useEffect(() => {
    if (isActive) validate();
    return () => {
      request.current?.abort();
      request.current = null;
      setRequestPending(false);
    };
  }, [cacheKey, isActive, refreshGeneration, mutate]);
  useEffect(() => {
    if (isVisible && isActive) validate();
  }, [isVisible, isActive]);

  return {
    data: result?.data,
    error: effectiveError,
    isValidating: isActive && (isValidating || requestPending),
    isCurrentGeneration: result?.refreshGeneration === refreshGeneration,
  };
}

interface OutputWebappsOptions {
  session: Pick<
    BuildSessionData,
    "sandbox" | "status" | "webappNeedsRefresh"
  > | null;
  sessionId: string | null;
  isOpen: boolean;
  hasBrowser: boolean;
  activeBrowser: boolean;
  appName: string;
}

/** Discover only registrations confirmed for the current session. */
export function useOutputWebapps({
  session,
  sessionId,
  isOpen,
  hasBrowser,
  activeBrowser,
  appName,
}: OutputWebappsOptions) {
  const { user } = useUser();
  const userId = user?.id;
  const runtimeUnavailable =
    session !== null && session.sandbox?.status !== "running";
  const canQuery =
    Boolean(userId) &&
    !!sessionId &&
    !sessionId.startsWith("temp-") &&
    session?.status !== "creating" &&
    !runtimeUnavailable;
  const {
    data: webappInfo,
    error: webappError,
    isValidating: webappChecking,
    mutate: refreshWebapps,
  } = useSWR<ApiWebappInfoResponse | null, Error>(
    hasBrowser && canQuery && isOpen
      ? [SWR_KEYS.buildSessionWebappInfo(sessionId), userId]
      : null,
    () => (sessionId ? fetchWebappInfo(sessionId) : null),
    {
      refreshInterval: isOpen && activeBrowser && canQuery ? 5000 : 0,
      revalidateOnMount: false,
      revalidateOnFocus: isOpen,
      onErrorRetry: skipRetryOnAuthError,
    }
  );
  const webappRevision = session?.webappNeedsRefresh ?? 0;
  const pendingWebappValidation = useRef<{ identity: string } | null>(null);
  useEffect(() => {
    if (!isOpen || !hasBrowser || !canQuery) return;
    const identity = JSON.stringify([userId, sessionId, webappRevision]);
    if (pendingWebappValidation.current?.identity === identity) return;
    const pending = { identity };
    pendingWebappValidation.current = pending;
    void refreshWebapps()
      .catch(() => undefined)
      .finally(() => {
        if (pendingWebappValidation.current === pending)
          pendingWebappValidation.current = null;
      });
  }, [
    isOpen,
    hasBrowser,
    canQuery,
    userId,
    sessionId,
    webappRevision,
    refreshWebapps,
  ]);

  const apps = useMemo<RegisteredWebapp[]>(
    () =>
      webappInfo?.has_webapp && webappInfo.webapp_url
        ? [
            {
              id: sessionId ?? "",
              name: appName,
              url: webappInfo.webapp_url,
              state:
                runtimeUnavailable || webappError
                  ? "unavailable"
                  : webappInfo.ready
                    ? "ready"
                    : "starting",
            },
          ]
        : [],
    [webappInfo, sessionId, appName, runtimeUnavailable, webappError]
  );
  const accessRevoked =
    isAuthStatusError(webappError) || isNotFoundError(webappError);
  const discoveryState: AppDiscoveryState = !canQuery
    ? "unavailable"
    : webappError
      ? "failed"
      : !webappInfo
        ? "checking"
        : "ready";
  return {
    apps,
    accessRevoked,
    discoveryState,
    canQuery,
    runtimeUnavailable,
    webappInfo,
    webappChecking,
    refreshWebapps,
  };
}

/** Updating a listener must not look like the request finished. */
export function useOutputRefreshStatus(
  refreshing: boolean,
  onChange?: (refreshing: boolean) => void
) {
  const notify = useEffectEvent((value: boolean) => onChange?.(value));
  useEffect(() => {
    notify(refreshing);
  }, [refreshing, onChange]);
  useEffect(() => () => notify(false), []);
}

/** Directory membership stays local; React only observes aggregate loading changes. */
export function useDirectoryLoading() {
  const pendingPaths = useRef(new Set<string>());
  const [isLoading, setIsLoading] = useState(false);
  const setDirectoryLoading = useCallback((path: string, loading: boolean) => {
    if (loading) pendingPaths.current.add(path);
    else pendingPaths.current.delete(path);
    setIsLoading(pendingPaths.current.size > 0);
  }, []);
  const hasPendingDirectories = useCallback(
    () => pendingPaths.current.size > 0,
    []
  );
  return { isLoading, setDirectoryLoading, hasPendingDirectories };
}
