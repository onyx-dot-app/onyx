"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useSettings } from "@/lib/settings/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { PersonSuggestions } from "@/lib/suggestedQuestions/types";

/** How often to check again while the server is preparing questions. */
const POLL_INTERVAL_MS = 10_000;
/** Stop checking after this long. It is one check longer than the server's
 * SQ_PREPARING_S (120 s), so the last check sees the server end "preparing"
 * and the page never keeps a stale "preparing". */
const POLL_FOR_MS = 120_000 + POLL_INTERVAL_MS;

// Module state lives as long as the page, so every caller shares it: the
// questions stay put while the page is open and change on reload.
let pageSeed: number | undefined;
function getPageSeed(): number {
  pageSeed ??= Math.floor(Math.random() * 2 ** 31);
  return pageSeed;
}
// When each agent's chat open reached the server, which also starts its
// polling window.
const openedAt = new Map<number, number>();

async function fetchSuggestions(
  url: string,
  agentId: number
): Promise<PersonSuggestions> {
  const opened = openedAt.has(agentId);
  const suggestions = await errorHandlingFetcher<PersonSuggestions>(
    `${url}&poll=${opened}`
  );
  // Only a request that succeeded counts as the chat open, so a failed one is
  // retried as an open, which may still ask for a run.
  if (!opened) {
    openedAt.set(agentId, Date.now());
  }
  return suggestions;
}

/**
 * How long to wait before checking again; 0 stops checking. Checks run every
 * POLL_INTERVAL_MS while the server is preparing questions, for POLL_FOR_MS
 * after the chat open.
 */
export function nextPollDelay(
  latest: PersonSuggestions | undefined,
  openedAtMs: number | undefined,
  nowMs: number
): number {
  const stillPreparing =
    latest?.state === "preparing" &&
    openedAtMs !== undefined &&
    nowMs - openedAtMs < POLL_FOR_MS;
  return stillPreparing ? POLL_INTERVAL_MS : 0;
}

/**
 * The person's suggested questions, on the Playground only. The first
 * successful fetch for an agent counts as a chat open: the server records
 * the visit and may ask for a run. Every later fetch (the checks while
 * "preparing") sends `poll=true` and only reads. Callers for the same agent
 * share one request.
 */
export function useSuggestedQuestions(agentId: number | null) {
  const { is_playground } = useSettings();

  const key: [string, number] | null =
    is_playground && agentId !== null
      ? [SWR_KEYS.suggestedQuestions(agentId, getPageSeed()), agentId]
      : null;

  const { data, mutate } = useSWR<PersonSuggestions>(
    key,
    ([url, id]: [string, number]) => fetchSuggestions(url, id),
    {
      revalidateOnFocus: false,
      refreshInterval: (latest) =>
        nextPollDelay(
          latest,
          agentId === null ? undefined : openedAt.get(agentId),
          Date.now()
        ),
    }
  );

  return { suggestions: data, mutate };
}
