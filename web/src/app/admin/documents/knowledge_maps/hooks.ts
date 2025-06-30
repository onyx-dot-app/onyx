import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR, { mutate } from "swr";
import { KnowledgeMapCreationRequest } from "./lib";

const KNOWLEDGE_MAPS_URL = "/api/knowledge/";

export function refreshKnowledgeMaps() {
  mutate(KNOWLEDGE_MAPS_URL);
}

export function useKnowledgeMaps() {
  const swrResponse = useSWR<KnowledgeMapCreationRequest[]>(
    KNOWLEDGE_MAPS_URL,
    errorHandlingFetcher,
    {
      refreshInterval: 5000, // 5 seconds
    }
  );

  return {
    ...swrResponse,
    refreshKnowledgeMaps: refreshKnowledgeMaps,
  };
}
