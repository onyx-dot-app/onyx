"use client";

import { useNavigation, useSearchParams } from "@opal/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getConfiguredSources } from "@/lib/connectors/utils";
import type { OnSubmitProps } from "@/hooks/useChatController";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import { SUBMIT_MESSAGE_TYPES } from "@/lib/extension/constants";
import { useAvailableSources } from "@/lib/connectors/hooks";
import { useDocumentSets } from "@/lib/hooks/useDocumentSets";
import { useProjectsContext } from "@/lib/projects/providers";
import { useTags } from "@/lib/searchFilters/hooks";
import { normalizeSourceSelection } from "@/lib/searchFilters/utils";
import type { ToolConfigurationHandle } from "@/lib/tools/hooks";

import useSWR, { useSWRConfig } from "swr";
import { useTranslations } from "next-intl";
import { toast } from "@opal/layouts";
import {
  errorHandlingFetcher,
  errorHandlingFetchWith,
  fetchErrorDetail,
  FetchError,
  skipRetryOnAuthError,
} from "@/lib/fetcher";
import { refreshChatSession } from "@/lib/chat/settleChatSession";
import type { ChatSessionStatus, PendingChatMessage } from "@/lib/chat/types";
import { getMessageByMessageId } from "@/app/app/services/messageTree";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { useShallow } from "zustand/react/shallow";

const EMPTY_PENDING_MESSAGES: PendingChatMessage[] = [];
const PENDING_MESSAGES_POLL_MS = 1000;
const SUBAGENT_ACTIVITY_POLL_MS = 2000;

/** Discover background work without making it part of the root response's busy state. */
export function useSubagentActivity(
  sessionId: string | null,
  enabled: boolean
) {
  const tReadiness = useTranslations("chat.readiness");
  const { chatState, hasActiveSubagents, readerFinished } = useChatSessionStore(
    useShallow((state) => {
      const session = sessionId ? state.sessions.get(sessionId) : undefined;
      return {
        chatState: session?.chatState,
        hasActiveSubagents: session?.hasActiveSubagents ?? false,
        readerFinished: session?.readerFinished,
      };
    })
  );
  const key =
    enabled && sessionId ? SWR_KEYS.chatSessionStatus(sessionId) : null;
  const refreshing = useRef(false);
  const { mutate } = useSWR<ChatSessionStatus, Error>(
    key,
    errorHandlingFetcher,
    {
      refreshInterval: (status) =>
        hasActiveSubagents ||
        status?.has_active_subagents ||
        chatState === "loading" ||
        chatState === "streaming" ||
        chatState === "cancelling"
          ? SUBAGENT_ACTIVITY_POLL_MS
          : 0,
      onErrorRetry: skipRetryOnAuthError,
      onSuccess: (status) => {
        if (!sessionId) return;
        const store = useChatSessionStore.getState();
        const session = store.sessions.get(sessionId);
        if (!session) return;
        if (session.hasActiveSubagents !== status.has_active_subagents) {
          store.updateSessionData(sessionId, {
            hasActiveSubagents: status.has_active_subagents,
          });
        }
        // A reply can finish between polls, so inspect its identity as well as liveness.
        if (
          session.chatState !== "input" ||
          refreshing.current ||
          status.latest_response_id === null ||
          (!status.is_processing &&
            getMessageByMessageId(
              session.messageTree,
              status.latest_response_id
            ))
        )
          return;
        refreshing.current = true;
        void refreshChatSession(sessionId, tReadiness("checkFailed")).finally(
          () => {
            refreshing.current = false;
          }
        );
      },
    }
  );
  useEffect(() => {
    if (!key || !readerFinished) return;
    let active = true;
    const refresh = () => {
      if (active)
        void mutate().catch((error: unknown) => {
          console.error("Could not refresh subagent activity", error);
        });
    };
    void readerFinished.then(refresh, refresh);
    return () => {
      active = false;
    };
  }, [key, mutate, readerFinished]);
  return enabled && hasActiveSubagents;
}

/** The server owns acceptance and ordering; this cache only displays pending input. */
export function usePendingChatMessages(
  sessionId: string | null,
  enabled: boolean
) {
  const t = useTranslations("chat.input.pendingMessages");
  const tReadiness = useTranslations("chat.readiness");
  const key =
    enabled && sessionId ? SWR_KEYS.pendingChatMessages(sessionId) : null;
  const { mutate: mutateCache } = useSWRConfig();
  const { readerFinished, sendAcknowledged } = useChatSessionStore(
    useShallow((state) => {
      const session = sessionId ? state.sessions.get(sessionId) : undefined;
      return {
        readerFinished: session?.readerFinished,
        sendAcknowledged: session?.sendAcknowledged,
      };
    })
  );
  useEffect(() => {
    if (!key) return;
    let active = true;
    const refresh = () => {
      if (!active) return;
      void mutateCache(key).catch((failure: unknown) =>
        console.error("Failed to refresh pending messages", failure)
      );
    };
    // A completed reader or a newly acknowledged turn can consume queued input.
    void readerFinished?.then(refresh, refresh);
    void sendAcknowledged?.then(refresh, refresh);
    return () => {
      active = false;
    };
  }, [key, mutateCache, readerFinished, sendAcknowledged]);
  const activeKey = useRef(key);
  useEffect(() => {
    activeKey.current = key;
  }, [key]);
  const [submittingSession, setSubmittingSession] = useState<string | null>(
    null
  );
  const submitting = useRef(false);
  const withdrawing = useRef(new Set<string>());
  const previous = useRef<{
    key: string | null;
    deliveries: Map<string, PendingChatMessage["delivery"]>;
  }>({ key: null, deliveries: new Map() });
  const { data, error, isLoading } = useSWR<PendingChatMessage[], Error>(
    key,
    async (url: string): Promise<PendingChatMessage[]> => {
      const messages = await errorHandlingFetcher<PendingChatMessage[]>(url);
      if (activeKey.current !== url || !sessionId) return messages;
      const ids = new Set(messages.map((message) => message.id));
      const accepted =
        previous.current.key === url
          ? [...previous.current.deliveries].filter(([id]) => !ids.has(id))
          : [];
      if (accepted.length > 0) {
        const refresh = refreshChatSession(
          sessionId,
          tReadiness("checkFailed")
        );
        // Show an accepted queued turn before removing its pending preview.
        if (accepted.some(([, delivery]) => delivery !== "send")) {
          await refresh;
        }
      }
      return messages;
    },
    {
      refreshInterval: (messages) =>
        messages?.length ? PENDING_MESSAGES_POLL_MS : 0,
      onErrorRetry: skipRetryOnAuthError,
      onSuccess: (messages) => {
        if (activeKey.current !== key) return;
        previous.current = {
          key,
          deliveries: new Map(
            messages.map((message) => [message.id, message.delivery])
          ),
        };
      },
    }
  );

  async function rememberPendingMessage(
    pending: PendingChatMessage
  ): Promise<void> {
    if (!key || !sessionId) return;
    // Revalidation may already omit an input accepted before the POST returned.
    await mutateCache<PendingChatMessage[]>(
      key,
      (messages = []) =>
        messages.some((item) => item.id === pending.id)
          ? messages.map((item) => (item.id === pending.id ? pending : item))
          : [...messages, pending],
      { revalidate: false }
    );
    if (activeKey.current === key) {
      previous.current = {
        key,
        deliveries: new Map([
          ...(previous.current.key === key ? previous.current.deliveries : []),
          [pending.id, pending.delivery],
        ]),
      };
    }
    void mutateCache(key).catch((failure: unknown) =>
      console.error("Failed to refresh pending messages", failure)
    );
  }

  async function submit(
    message: string,
    delivery: PendingChatMessage["delivery"],
    targetResponseId: number
  ): Promise<boolean> {
    if (!key || !sessionId || submitting.current) return false;
    submitting.current = true;
    setSubmittingSession(sessionId);
    try {
      const pending = await errorHandlingFetchWith<PendingChatMessage>(key, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          delivery,
          target_response_id: targetResponseId,
        }),
      });
      await rememberPendingMessage(pending);
      return true;
    } catch (failure) {
      toast.error(fetchErrorDetail(failure) ?? t("submitFailed"));
      return false;
    } finally {
      submitting.current = false;
      setSubmittingSession(null);
    }
  }

  async function interrupt(id: string): Promise<boolean> {
    const queued = data?.find((message) => message.id === id);
    if (!key || !sessionId || !queued || submitting.current) return false;
    const target =
      queued.target_response_id === null
        ? ""
        : `?target_response_id=${queued.target_response_id}`;
    submitting.current = true;
    setSubmittingSession(sessionId);
    try {
      const pending = await errorHandlingFetchWith<PendingChatMessage>(
        `${key}/${id}/interrupt${target}`,
        { method: "POST" }
      );
      await rememberPendingMessage(pending);
      return true;
    } catch (failure) {
      toast.error(
        failure instanceof FetchError && failure.status === 409
          ? t("alreadyAccepted")
          : (fetchErrorDetail(failure) ?? t("interruptFailed"))
      );
      void mutateCache(key).catch((refreshFailure: unknown) =>
        console.error("Failed to refresh pending messages", refreshFailure)
      );
      return false;
    } finally {
      submitting.current = false;
      setSubmittingSession(null);
    }
  }

  async function withdraw(id: string): Promise<PendingChatMessage | null> {
    if (!key || !sessionId || withdrawing.current.has(id)) return null;
    withdrawing.current.add(id);
    try {
      const withdrawn = await errorHandlingFetchWith<PendingChatMessage>(
        `${key}/${id}`,
        { method: "DELETE" }
      );
      await mutateCache<PendingChatMessage[]>(
        key,
        (messages = []) => messages.filter((item) => item.id !== id),
        { revalidate: false }
      );
      if (previous.current.key === key) previous.current.deliveries.delete(id);
      void refreshChatSession(sessionId, tReadiness("checkFailed"));
      return withdrawn;
    } catch (failure) {
      toast.error(
        failure instanceof FetchError && failure.status === 409
          ? t("alreadyAccepted")
          : (fetchErrorDetail(failure) ?? t("withdrawFailed"))
      );
      return null;
    } finally {
      withdrawing.current.delete(id);
      void mutateCache(key).catch((failure: unknown) =>
        console.error("Failed to refresh pending messages", failure)
      );
    }
  }

  return {
    messages: data ?? EMPTY_PENDING_MESSAGES,
    isLoading,
    isSubmitting: submittingSession === sessionId && submittingSession !== null,
    error: error ? t("loadFailed") : null,
    submit,
    interrupt,
    withdraw,
  };
}

interface UseSendChatMessageFromURLProps {
  /** From `useChatController`, which needs more than this hook can see. */
  onSubmit: (props: OnSubmitProps) => void;
  /** Resolved against the active project, so the page decides it, not this. */
  deepResearch: boolean;
  /** Where the filters a URL names are written: the chat's own configuration. */
  toolConfiguration: ToolConfigurationHandle;
}

/**
 * Sends the message a URL asks for, scoped by the filters that URL names.
 *
 * A link into the app can carry both a prompt and a search scope —
 * `?sources=slack&user-prompt=…&send-on-load=true` — which is how the Chrome
 * extension, an agent preview, and a shared link all open a chat that is
 * already narrowed and already asking.
 *
 * Two arrivals are handled: the page loading with `send-on-load` set, and a
 * `PAGE_CHANGE` message posted by the extension while the page stays put.
 * Both queue the query rather than sending in place, because sending is
 * gated twice:
 *
 * 1. A query naming sources, sets or tags waits for that data to settle —
 *    resolving names against a list still in flight would scope the send
 *    wrong and persist that wrong scope on the chat. A fetch that errors
 *    counts as settled: its names match nothing, so that dimension falls
 *    back to unfiltered — the pre-refactor behavior — rather than the
 *    send waiting forever.
 * 2. The submit happens one render after the filters are written, so it
 *    reads the configuration it just scoped instead of the previous one.
 *
 * `send-on-load` is stripped from the URL afterwards, so a refresh does not
 * send the message a second time.
 *
 * Everything reachable from context is read here — the filters, the project's
 * files, and the sources, sets and tags a name resolves against. Only the
 * submit itself and the deep-research flag come from the caller, because
 * neither is context.
 */
export function useSendChatMessageFromURL({
  onSubmit,
  deepResearch,
  toolConfiguration,
}: UseSendChatMessageFromURLProps) {
  const navigation = useNavigation();
  const searchParams = useSearchParams();

  const { currentMessageFiles } = useProjectsContext();
  const {
    availableSources,
    isLoading: sourcesLoading,
    settled: sourcesSettled,
  } = useAvailableSources();
  const { documentSets, isLoading: documentSetsLoading } = useDocumentSets();
  const { tags, isLoading: tagsLoading } = useTags();

  const configuredSources = useMemo(
    () => getConfiguredSources(availableSources),
    [availableSources]
  );

  const [queuedQuery, setQueuedQueryState] = useState<string | null>(null);
  // The page that queued the query. The page being left stays mounted (and
  // hidden) while the next one renders, so a query that settles after the
  // user moved on must not write to the new page's URL or send.
  const queuedPathnameRef = useRef<string | null>(null);
  const setQueuedQuery = useCallback((query: string | null) => {
    queuedPathnameRef.current =
      query === null ? null : window.location.pathname;
    setQueuedQueryState(query);
  }, []);
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);

  // Arriving with the parameters already on the URL.
  //
  // Guarded because `navigation.go` only drops `send-on-load` a tick after
  // the query is processed — without this the effect re-runs inside that
  // window and queues the same prompt twice.
  const sentForRef = useRef<string | null>(null);
  useEffect(() => {
    if (!searchParams?.get(SEARCH_PARAM_NAMES.SEND_ON_LOAD)) return;
    const query = searchParams.toString();
    if (sentForRef.current === query) return;
    sentForRef.current = query;
    setQueuedQuery(query);
  }, [searchParams, setQueuedQuery]);

  // The extension navigating the embedded page without a reload.
  useEffect(() => {
    function onPageChange(event: MessageEvent) {
      if (event.data.type !== SUBMIT_MESSAGE_TYPES.PAGE_CHANGE) return;
      try {
        setQueuedQuery(new URL(event.data.href).searchParams.toString());
      } catch (error) {
        console.error("Error parsing URL:", error);
      }
    }

    window.addEventListener("message", onPageChange);
    return () => window.removeEventListener("message", onPageChange);
  }, [setQueuedQuery]);

  // Processes the queued query once every dimension it names has settled.
  // Re-runs as the loading flags flip, so a query that arrived early waits
  // here instead of resolving names against half-fetched lists.
  useEffect(() => {
    if (queuedQuery === null) return;
    if (window.location.pathname !== queuedPathnameRef.current) {
      // Not handled, so the same URL can queue it again on a return.
      sentForRef.current = null;
      setQueuedQuery(null);
      return;
    }
    // Writes are dropped until the composer's configuration binds to its
    // chat, so processing earlier would scope nothing and persist nothing.
    if (!toolConfiguration.ready) return;

    const params = new URLSearchParams(queuedQuery);
    const message = params.get(SEARCH_PARAM_NAMES.USER_PROMPT);

    // Names that match nothing available are dropped, so a stale or
    // hand-typed link narrows the search rather than failing it.
    // URLSearchParams already percent-decoded the value; decoding again
    // would corrupt names and throw on a legitimate literal like "100%".
    const namesIn = (param: string): string[] =>
      params.get(param)?.split(",") ?? [];

    const sourceNames = namesIn("sources");
    const docSetNames = namesIn("documentSets");
    const tagValues = namesIn("tags");

    if (
      (sourceNames.length > 0 && sourcesLoading) ||
      (docSetNames.length > 0 && documentSetsLoading) ||
      (tagValues.length > 0 && tagsLoading)
    ) {
      return;
    }
    setQueuedQuery(null);

    const from = new Date(params.get("from") ?? "");
    const to = new Date(params.get("to") ?? "");
    const hasRange = !isNaN(from.getTime()) && !isNaN(to.getTime());

    // Only the dimensions the URL names are written; the rest keep what the
    // chat already holds — an agent-viewer hand-off arrives with picks this
    // must not clear. A failed source fetch also leaves sources untouched:
    // writing a selection derived from a partial list would persist a wrong
    // scope, where one wide send does not.
    toolConfiguration.setFilters((current) => ({
      selectedSources:
        sourceNames.length > 0 && sourcesSettled
          ? normalizeSourceSelection(
              configuredSources
                .filter((source) => sourceNames.includes(source.internalName))
                .map((source) => source.uniqueKey),
              configuredSources.map((source) => source.uniqueKey)
            )
          : current.selectedSources,
      documentSets:
        docSetNames.length > 0
          ? documentSets
              .map((ds) => ds.name)
              .filter((name) => docSetNames.includes(name))
          : current.documentSets,
      tags:
        tagValues.length > 0
          ? tags.filter((tag) => tagValues.includes(tag.tag_value))
          : current.tags,
      timeRange: hasRange
        ? { from: from.toISOString(), to: to.toISOString() }
        : current.timeRange,
    }));

    // Dropped before the replace so a refresh does not resend.
    params.delete(SEARCH_PARAM_NAMES.SEND_ON_LOAD);
    navigation.go(`?${params.toString()}`, { replace: true, scroll: false });

    if (message) setPendingMessage(message);
  }, [
    queuedQuery,
    sourcesLoading,
    sourcesSettled,
    documentSetsLoading,
    tagsLoading,
    configuredSources,
    documentSets,
    tags,
    navigation,
    toolConfiguration,
    setQueuedQuery,
  ]);

  // Submits one render after the filter write above landed, so `onSubmit`'s
  // closure reads the configuration the query scoped, not the previous one.
  useEffect(() => {
    if (pendingMessage === null) return;
    setPendingMessage(null);
    onSubmit({ message: pendingMessage, currentMessageFiles, deepResearch });
  }, [pendingMessage, onSubmit, currentMessageFiles, deepResearch]);
}
