import type { TFunction } from "i18next";
import {
  CODING_AGENT_TOOL_ID,
  IMAGE_GENERATION_TOOL_ID,
  OPEN_URL_TOOL_ID,
  PYTHON_TOOL_ID,
  SEARCH_TOOL_ID,
  WEB_SEARCH_TOOL_ID,
} from "@/app/app/components/tools/constants";
import type { ToolSnapshot } from "@/lib/tools/interfaces";

const TOOL_LABEL_KEYS: Record<string, string> = {
  [SEARCH_TOOL_ID]: "tools.internal_search",
  [IMAGE_GENERATION_TOOL_ID]: "tools.image_gen",
  [WEB_SEARCH_TOOL_ID]: "tools.web_search",
  [PYTHON_TOOL_ID]: "tools.code_interpreter",
  [CODING_AGENT_TOOL_ID]: "tools.coding_agent",
  [OPEN_URL_TOOL_ID]: "tools.open_url",
};

export function getLocalizedToolLabel(
  tool: Pick<ToolSnapshot, "in_code_tool_id" | "display_name" | "name">,
  t: TFunction
): string {
  const toolKey = tool.in_code_tool_id || tool.name;
  if (toolKey && TOOL_LABEL_KEYS[toolKey]) {
    return t(TOOL_LABEL_KEYS[toolKey]);
  }
  return tool.display_name || tool.name;
}
