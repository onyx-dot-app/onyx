import { ResponseItem } from "@/chat/streamingModels";
import { firstTool } from "@/chat/responseItems";

export const isResearchAgentItems = (items: ResponseItem[]): boolean =>
  firstTool(items)?.name === "research_agent";
export const isCodingAgentItems = (items: ResponseItem[]): boolean =>
  firstTool(items)?.name === "coding_agent";
export const isSearchToolItems = (items: ResponseItem[]): boolean =>
  ["internal_search", "web_search"].includes(firstTool(items)?.name ?? "");
export const isPythonToolItems = (items: ResponseItem[]): boolean =>
  ["python", "run_python"].includes(firstTool(items)?.name ?? "");
export const isMemoryToolItems = (items: ResponseItem[]): boolean =>
  firstTool(items)?.name === "add_memory";
export const stepSupportsCollapsedStreaming = (
  items: ResponseItem[],
): boolean =>
  items.some(
    (item) =>
      item.content.kind !== "tool" || item.content.name !== "generate_image",
  );
export const stepHasCollapsedStreamingContent = (
  items: ResponseItem[],
): boolean =>
  items.some((item) =>
    item.content.kind === "tool"
      ? Object.keys(item.content.arguments).length > 0 ||
        item.content.metadata !== null ||
        !!item.content.output
      : !!item.content.text,
  );
