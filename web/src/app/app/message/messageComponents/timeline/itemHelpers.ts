import {
  ResponseItem,
  isCodeInterpreterToolType,
} from "@/app/app/services/streamingModels";
import { constructCurrentSearchState } from "@/app/app/message/messageComponents/timeline/renderers/search/searchStateUtils";
import { constructCurrentFetchState } from "@/app/app/message/messageComponents/timeline/renderers/fetch/fetchStateUtils";
import { firstTool } from "@/app/app/services/responseItems";

export const isResearchAgentItems = (items: ResponseItem[]): boolean =>
  firstTool(items)?.name === "research_agent";
export const isCodingAgentItems = (items: ResponseItem[]): boolean =>
  ["coding_agent", "bash"].includes(firstTool(items)?.name ?? "");
export const isSearchToolItems = (items: ResponseItem[]): boolean =>
  ["internal_search", "web_search"].includes(firstTool(items)?.name ?? "");
export const isPythonToolItems = (items: ResponseItem[]): boolean =>
  items.some(
    (item) =>
      item.content.kind === "tool" &&
      isCodeInterpreterToolType(item.content.name)
  );
export const isReasoningItems = (items: ResponseItem[]): boolean =>
  items.some((item) => item.content.kind === "reasoning");
export const isDeepResearchPlanItems = (items: ResponseItem[]): boolean =>
  items.some(
    (item) => item.content.kind === "text" && item.content.purpose === "plan"
  );
export const isMemoryToolItems = (items: ResponseItem[]): boolean =>
  firstTool(items)?.name === "add_memory";

export function stepSupportsCollapsedStreaming(items: ResponseItem[]): boolean {
  return items.some(
    (item) => item.content.kind !== "text" || item.content.purpose !== "answer"
  );
}

export function stepHasCollapsedStreamingContent(
  items: ResponseItem[]
): boolean {
  const tool = firstTool(items);
  if (tool?.status === "error" && tool.metadata === null) {
    return tool.output.length > 0;
  }
  if (tool?.name === "internal_search" || tool?.name === "web_search") {
    const search = constructCurrentSearchState(items);
    return search.queries.length > 0 || search.results.length > 0;
  }
  if (tool?.name === "open_url") {
    const fetch = constructCurrentFetchState(items);
    return (
      fetch.documents.length > 0 || (fetch.isComplete && fetch.urls.length > 0)
    );
  }
  return items.some((item) =>
    item.content.kind === "tool"
      ? item.content.metadata !== null ||
        item.content.output.length > 0 ||
        Object.keys(item.content.arguments).length > 0
      : item.content.text.length > 0
  );
}
