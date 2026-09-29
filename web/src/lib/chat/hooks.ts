"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { OnSubmitProps } from "@/hooks/useChatController";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import { SUBMIT_MESSAGE_TYPES } from "@/lib/extension/constants";
import { useAvailableSources } from "@/lib/connectors/hooks";
import { useDocumentSets } from "@/lib/hooks/useDocumentSets";
import { useProjectsContext } from "@/lib/projects/providers";
import { useTags } from "@/lib/searchFilters/hooks";
import { normalizeSourceSelection } from "@/lib/searchFilters/utils";
import { getConfiguredSources } from "@/lib/sources";
import type { ToolConfigurationHandle } from "@/lib/tools/hooks";

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
  const router = useRouter();
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

  const [queuedQuery, setQueuedQuery] = useState<string | null>(null);
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);

  // Arriving with the parameters already on the URL.
  //
  // Guarded because `router.replace` only drops `send-on-load` a tick after
  // the query is processed — without this the effect re-runs inside that
  // window and queues the same prompt twice.
  const sentForRef = useRef<string | null>(null);
  useEffect(() => {
    if (!searchParams?.get(SEARCH_PARAM_NAMES.SEND_ON_LOAD)) return;
    const query = searchParams.toString();
    if (sentForRef.current === query) return;
    sentForRef.current = query;
    setQueuedQuery(query);
  }, [searchParams]);

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
  }, []);

  // Processes the queued query once every dimension it names has settled.
  // Re-runs as the loading flags flip, so a query that arrived early waits
  // here instead of resolving names against half-fetched lists.
  useEffect(() => {
    if (queuedQuery === null) return;
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
    router.replace(`?${params.toString()}`, { scroll: false });

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
    router,
    toolConfiguration,
  ]);

  // Submits one render after the filter write above landed, so `onSubmit`'s
  // closure reads the configuration the query scoped, not the previous one.
  useEffect(() => {
    if (pendingMessage === null) return;
    setPendingMessage(null);
    onSubmit({ message: pendingMessage, currentMessageFiles, deepResearch });
  }, [pendingMessage, onSubmit, currentMessageFiles, deepResearch]);
}
