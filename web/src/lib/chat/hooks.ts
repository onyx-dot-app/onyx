"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { OnSubmitProps } from "@/hooks/useChatController";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import { SUBMIT_MESSAGE_TYPES } from "@/lib/extension/constants";
import { useAvailableSources } from "@/lib/connectors/hooks";
import { useDocumentSets } from "@/lib/hooks/useDocumentSets";
import { useProjectsContext } from "@/lib/projects/providers";
import type { SourceMetadata } from "@/lib/search/interfaces";
import { useTags } from "@/lib/searchFilters/hooks";
import { useSharedSearchFilters } from "@/lib/searchFilters/providers";
import { getSourceMetadata } from "@/lib/sources";

interface UseSendChatMessageFromURLProps {
  /** From `useChatController`, which needs more than this hook can see. */
  onSubmit: (props: OnSubmitProps) => void;
  /** Resolved against the active project, so the page decides it, not this. */
  deepResearch: boolean;
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
}: UseSendChatMessageFromURLProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const searchFilters = useSharedSearchFilters();
  const { currentMessageFiles } = useProjectsContext();
  const { availableSources } = useAvailableSources();
  const { documentSets } = useDocumentSets();
  const { tags } = useTags();

  const sources: SourceMetadata[] = useMemo(() => {
    const seen = new Set<string>();
    return availableSources.reduce<SourceMetadata[]>((acc, source) => {
      const metadata = getSourceMetadata(source);
      if (seen.has(metadata.internalName)) return acc;
      seen.add(metadata.internalName);
      acc.push(metadata);
      return acc;
    }, []);
  }, [availableSources]);

  const send = useCallback(
    (searchParamsString: string) => {
      const params = new URLSearchParams(searchParamsString);
      const message = params.get(SEARCH_PARAM_NAMES.USER_PROMPT);

      // Names that match nothing available are dropped, so a stale or
      // hand-typed link narrows the search rather than failing it.
      const namesIn = (param: string): string[] =>
        params.get(param)?.split(",").map(decodeURIComponent) ?? [];

      const from = new Date(params.get("from") ?? "");
      const to = new Date(params.get("to") ?? "");
      const hasRange = !isNaN(from.getTime()) && !isNaN(to.getTime());
      searchFilters.setTimeRange(
        hasRange ? { from, to, selectValue: "" } : null
      );

      const sourceNames = namesIn("sources");
      searchFilters.setSelectedSources(
        sources.filter((source) => sourceNames.includes(source.internalName))
      );

      const docSetNames = namesIn("documentSets");
      searchFilters.setSelectedDocumentSets(
        documentSets
          .map((ds) => ds.name)
          .filter((name) => docSetNames.includes(name))
      );

      const tagValues = namesIn("tags");
      searchFilters.setSelectedTags(
        tags.filter((tag) => tagValues.includes(tag.tag_value))
      );

      // Dropped before the replace so a refresh does not resend.
      params.delete(SEARCH_PARAM_NAMES.SEND_ON_LOAD);
      router.replace(`?${params.toString()}`, { scroll: false });

      if (!message) return;

      onSubmit({ message, currentMessageFiles, deepResearch });
    },
    [
      router,
      searchFilters,
      sources,
      documentSets,
      tags,
      currentMessageFiles,
      deepResearch,
      onSubmit,
    ]
  );

  // Arriving with the parameters already on the URL.
  //
  // Guarded because `send` changes identity as the filters, sets, tags and
  // project files resolve, and `router.replace` only drops `send-on-load` a
  // tick later — so without this the effect re-runs inside that window and
  // sends the same prompt twice.
  const sentForRef = useRef<string | null>(null);
  useEffect(() => {
    if (!searchParams?.get(SEARCH_PARAM_NAMES.SEND_ON_LOAD)) return;
    const query = searchParams.toString();
    if (sentForRef.current === query) return;
    sentForRef.current = query;
    send(query);
  }, [searchParams, send]);

  // The extension navigating the embedded page without a reload.
  useEffect(() => {
    function onPageChange(event: MessageEvent) {
      if (event.data.type !== SUBMIT_MESSAGE_TYPES.PAGE_CHANGE) return;
      try {
        send(new URL(event.data.href).searchParams.toString());
      } catch (error) {
        console.error("Error parsing URL:", error);
      }
    }

    window.addEventListener("message", onPageChange);
    return () => window.removeEventListener("message", onPageChange);
  }, [send]);
}
