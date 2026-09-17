import { ResponseItem } from "@/chat/streamingModels";
import { firstTool, isComplete } from "@/chat/responseItems";
export function hasToolError(items: ResponseItem[]): boolean {
  return items.some((item) => item.content.status === "error");
}
export function isToolComplete(items: ResponseItem[]): boolean {
  const root = items.find((item) => item.placement.sub_turn_index == null);
  return root ? isComplete([root]) : isComplete(items);
}
export function getToolKey(turn_index: number, tab_index: number): string {
  return `${turn_index}-${tab_index}`;
}
export function parseToolKey(key: string): {
  turn_index: number;
  tab_index: number;
} {
  const [turn, tab] = key.split("-");
  return { turn_index: Number(turn), tab_index: Number(tab) };
}
export function getToolName(items: ResponseItem[]): string {
  const content = items[0]?.content;
  if (content?.kind === "reasoning") return "Thinking";
  if (content?.kind === "text")
    return content.purpose === "plan" ? "Generate plan" : "Response";
  const tool = firstTool(items);
  switch (tool?.name) {
    case "internal_search":
      return "Internal Search";
    case "web_search":
      return "Web Search";
    case "python":
    case "run_python":
      return "Code Interpreter";
    case "open_url":
      return "Open URLs";
    case "generate_image":
      return "Generate Image";
    case "research_agent":
      return "Research agent";
    case "coding_agent":
      return "Coding agent";
    case "add_memory":
      return "Memory";
    default:
      return tool?.name ?? "Tool";
  }
}
