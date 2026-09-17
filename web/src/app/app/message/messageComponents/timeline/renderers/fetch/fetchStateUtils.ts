import { ResponseItem } from "@/app/app/services/streamingModels";
import { OnyxDocument } from "@/lib/search/types";
import {
  firstTool,
  isComplete as itemsComplete,
  toolMetadata,
} from "@/app/app/services/responseItems";

export const INITIAL_URLS_TO_SHOW = 3;
export const URLS_PER_EXPANSION = 5;
export const READING_MIN_DURATION_MS = 1000;
export const READ_MIN_DURATION_MS = 1000;

export interface FetchState {
  urls: string[];
  documents: OnyxDocument[];
  hasStarted: boolean;
  isLoading: boolean;
  isComplete: boolean;
}

export function constructCurrentFetchState(items: ResponseItem[]): FetchState {
  const tool = firstTool(items);
  const result = toolMetadata(items, "search_result").at(-1);
  const documents = result?.displayed_docs ?? result?.search_docs ?? [];
  const urls = tool?.arguments.urls;
  return {
    urls: Array.isArray(urls)
      ? urls.filter((url): url is string => typeof url === "string")
      : [],
    documents,
    hasStarted: !!tool,
    isLoading: !!tool && !itemsComplete(items),
    isComplete: itemsComplete(items),
  };
}
