import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { Topic } from "./lib";

export function refreshTopics() {
  mutate(SWR_KEYS.topics);
}

export function useTopics() {
  const swrResponse = useSWR<Topic[]>(SWR_KEYS.topics, errorHandlingFetcher, {
    refreshInterval: 5000,
  });
  return { ...swrResponse, refreshTopics };
}
