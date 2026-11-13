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
import {
  flushToolSelection,
  type ToolConfigurationHandle,
} from "@/lib/tools/hooks";

import useSWR, { useSWRConfig } from "swr";
import { useTranslations } from "next-intl";
import { useShallow } from "zustand/react/shallow";
import { toast } from "@opal/layouts";
import {
  errorHandlingFetcher,
  errorHandlingFetchWith,
  fetchErrorDetail,
  FetchError,
  skipRetryOnAuthError,
} from "@/lib/fetcher";
import { refreshChatSession } from "@/lib/chat/settleChatSession";
import type {
  ChatSessionQueue,
  ChatSessionStatus,
  ComposedMessage,
  Mention,
  PendingChatMessage,
} from "@/lib/chat/types";
import {
  getLatestMessageChain,
  getMessageByMessageId,
  type MessageTreeState,
} from "@/app/app/services/messageTree";
import { getUnresolvedMultiModelTurn } from "@/app/app/message/multiModel";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";

const EMPTY_PENDING_MESSAGES: PendingChatMessage[] = [];
const SERVER_WORK_POLL_MS = 2000;

/** The response new input continues. Without a saved ID the server targets the running one. */
function pendingInputTarget(tree: MessageTreeState | undefined) {
  if (!tree) return { needsResponseSelection: false, targetResponseId: null };
  const history = getLatestMessageChain(tree);
  const needsResponseSelection = Boolean(
    getUnresolvedMultiModelTurn(history, tree)
  );
  const latest = history.at(-1);
  return {
    needsResponseSelection,
    targetResponseId:
      latest?.type === "assistant" &&
      latest.messageId != null &&
      latest.messageId > 0 &&
      !needsResponseSelection
        ? latest.messageId
        : null,
  };
}

/**
 * Server-owned pending messages and background activity of the current chat.
 * Mount once per chat surface; the composer only renders the result.
 */
export function useChatSessionQueue(enabled: boolean): ChatSessionQueue {
  const t = useTranslations("chat.input.pendingMessages");
  const tReadiness = useTranslations("chat.readiness");
  // Primitives only: the message tree changes on every streamed frame.
  const { sessionId, idle, needsResponseSelection } = useChatSessionStore(
    useShallow((state) => {
      const session = state.currentSessionId
        ? state.sessions.get(state.currentSessionId)
        : undefined;
      const target = pendingInputTarget(session?.messageTree);
      return {
        sessionId: state.currentSessionId,
        idle: session?.chatState === "input" && !session.isFetchingChatMessages,
        needsResponseSelection: target.needsResponseSelection,
      };
    })
  );
  const pendingKey =
    enabled && sessionId ? SWR_KEYS.pendingChatMessages(sessionId) : null;
  const statusKey =
    enabled && sessionId ? SWR_KEYS.chatSessionStatus(sessionId) : null;

  // Key-addressed, unlike the mutate useSWR returns, which follows the current key.
  const { mutate } = useSWRConfig();
  const { data: messages, error } = useSWR<PendingChatMessage[], Error>(
    pendingKey,
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError }
  );
  const { data: status } = useSWR<ChatSessionStatus, Error>(
    statusKey,
    errorHandlingFetcher,
    {
      // Pending input and background work can start a turn this client did not send.
      refreshInterval: (current) =>
        current?.has_startable_input || current?.has_active_subagents
          ? SERVER_WORK_POLL_MS
          : 0,
      onErrorRetry: skipRetryOnAuthError,
    }
  );

  // A reader owns a busy session; an idle one attaches to turns the server
  // started, whichever status read found them.
  const checkFailed = tReadiness("checkFailed");
  useEffect(() => {
    if (!sessionId || !status || !idle) return;
    const session = useChatSessionStore.getState().sessions.get(sessionId);
    if (!session) return;
    const missingResponse =
      status.latest_response_id !== null &&
      !getMessageByMessageId(session.messageTree, status.latest_response_id);
    if (status.is_processing || missingResponse)
      void refreshChatSession(sessionId, checkFailed);
  }, [sessionId, status, idle, checkFailed]);

  // Every turn saves a new response, so a new latest response means a turn
  // may have taken pending input, whoever started it and whether or not this
  // browser read its stream.
  const latestResponseId = status?.latest_response_id;
  const seenResponse = useRef<{
    sessionId: string | null;
    responseId: number | null | undefined;
  }>({ sessionId, responseId: latestResponseId });
  useEffect(() => {
    const previous = seenResponse.current;
    seenResponse.current = { sessionId, responseId: latestResponseId };
    if (
      pendingKey &&
      previous.sessionId === sessionId &&
      previous.responseId !== undefined &&
      latestResponseId !== undefined &&
      latestResponseId !== previous.responseId
    )
      void mutate(pendingKey);
  }, [sessionId, latestResponseId, pendingKey, mutate]);

  // One request per chat at a time. The composer keeps new input until it ends.
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const busy = busyKey !== null && busyKey === pendingKey;
  const hasActiveSubagents = status?.has_active_subagents ?? false;

  return useMemo(() => {
    // A 409 means the server already accepted the message.
    function toastPendingFailure(error: unknown, fallback: string) {
      toast.error(
        error instanceof FetchError && error.status === 409
          ? t("alreadyAccepted")
          : (fetchErrorDetail(error) ?? fallback)
      );
    }

    // Writes after an await target the chat that made the request.
    async function request<T>(
      action: (key: string) => Promise<T>
    ): Promise<T | null> {
      const key = pendingKey;
      const status = statusKey;
      if (!key || !status || busy) return null;
      setBusyKey(key);
      try {
        return await action(key);
      } finally {
        setBusyKey((current) => (current === key ? null : current));
        // A write can make input startable, and only a fresh status polls for
        // the turn that takes it.
        void mutate(status);
      }
    }

    return {
      enabled,
      messages: messages ?? EMPTY_PENDING_MESSAGES,
      error: error ? t("loadFailed") : null,
      busy,
      hasActiveSubagents,
      needsResponseSelection,
      submit: async ({ message, mentions }, delivery, turn) =>
        (await request(async (key) => {
          const session = sessionId
            ? useChatSessionStore.getState().sessions.get(sessionId)
            : undefined;
          // A turn the server starts reads the chat's saved tools.
          if (sessionId) await flushToolSelection(sessionId);
          try {
            const accepted = await errorHandlingFetchWith<PendingChatMessage>(
              key,
              {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  message,
                  delivery,
                  target_response_id: pendingInputTarget(session?.messageTree)
                    .targetResponseId,
                  deep_research: turn.deepResearch,
                  llm_override: turn.llmOverride,
                  mentions,
                }),
              }
            );
            // Revalidates after the write, since a turn can consume it at once.
            void mutate<PendingChatMessage[]>(key, (current = []) => [
              ...current,
              accepted,
            ]);
            return true;
          } catch (failure) {
            toast.error(fetchErrorDetail(failure) ?? t("submitFailed"));
            return false;
          }
        })) ?? false,
      withdraw: (id) =>
        request(async (key) => {
          try {
            const withdrawn = await errorHandlingFetchWith<PendingChatMessage>(
              `${key}/${id}`,
              { method: "DELETE" }
            );
            void mutate<PendingChatMessage[]>(
              key,
              (current = []) => current.filter((message) => message.id !== id),
              { revalidate: false }
            );
            return withdrawn;
          } catch (failure) {
            toastPendingFailure(failure, t("withdrawFailed"));
            void mutate(key);
            return null;
          }
        }),
      interrupt: async (id) => {
        await request(async (key) => {
          if (sessionId) await flushToolSelection(sessionId);
          try {
            await errorHandlingFetchWith<PendingChatMessage>(
              `${key}/${id}/interrupt`,
              { method: "POST" }
            );
          } catch (failure) {
            toastPendingFailure(failure, t("interruptFailed"));
          } finally {
            void mutate(key);
          }
        });
      },
      stopSubagents: async () => {
        const status = statusKey;
        if (!sessionId || !status) return;
        try {
          await errorHandlingFetchWith<unknown>(
            `/api/chat/chat-session/${sessionId}/stop-subagents`,
            { method: "POST" }
          );
        } catch (failure) {
          toast.error(fetchErrorDetail(failure) ?? t("stopSubagentsFailed"));
        } finally {
          void mutate(status);
        }
      },
    };
  }, [
    enabled,
    messages,
    error,
    busy,
    hasActiveSubagents,
    needsResponseSelection,
    sessionId,
    pendingKey,
    statusKey,
    mutate,
    t,
  ]);
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
  const [pendingMessage, setPendingMessage] = useState<ComposedMessage | null>(
    null
  );

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
      // A search sends only the start of a range.
      timeRange: hasRange ? { from: from.toISOString() } : current.timeRange,
    }));

    // Dropped before the replace so a refresh does not resend.
    params.delete(SEARCH_PARAM_NAMES.SEND_ON_LOAD);
    navigation.go(`?${params.toString()}`, { replace: true, scroll: false });

    if (message)
      setPendingMessage({
        message,
        mentions: namesIn(SEARCH_PARAM_NAMES.SKILLS).map(
          (name): Mention => ({ type: "skill", name })
        ),
      });
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
    onSubmit({
      ...pendingMessage,
      currentMessageFiles,
      deepResearch,
    });
  }, [pendingMessage, onSubmit, currentMessageFiles, deepResearch]);
}
