// Mirrors web actionUtils.ts getIconForAction(). Deviation: OpenURL →
// SvgExternalLink (mobile has no rotated chain-link SvgLink).
import type { ComponentType } from "react";

import {
  SvgCpu,
  SvgExternalLink,
  SvgGlobe,
  SvgImage,
  SvgSearch,
  SvgServer,
  SvgTerminal,
  type IconProps,
} from "@/components/icons";
import type { ToolSnapshot } from "@/lib/types/tools";

type IconComponent = ComponentType<IconProps>;

// First-match-wins; a tool matches on any of ids / names / displayIncludes.
interface ActionIconRule {
  icon: IconComponent;
  ids?: string[];
  names?: string[];
  displayIncludes?: string[];
}

const ACTION_ICON_RULES: ActionIconRule[] = [
  { icon: SvgSearch, ids: ["SearchTool"], names: ["run_search"], displayIncludes: ["search tool"] },
  { icon: SvgGlobe, ids: ["WebSearchTool"], displayIncludes: ["web_search"] },
  { icon: SvgImage, ids: ["ImageGenerationTool"], displayIncludes: ["image generation"] },
  { icon: SvgServer, ids: ["KnowledgeGraphTool"], displayIncludes: ["knowledge graph"] },
  { icon: SvgExternalLink, ids: ["OpenURLTool"], names: ["open_url"], displayIncludes: ["open url"] },
  { icon: SvgTerminal, ids: ["PythonTool"], names: ["python"], displayIncludes: ["code interpreter"] },
  { icon: SvgCpu, ids: ["CodingAgentTool"], names: ["coding_agent"], displayIncludes: ["coding agent"] },
];

function matchesRule(tool: ToolSnapshot, rule: ActionIconRule): boolean {
  const display = tool.display_name?.toLowerCase();
  return (
    (!!tool.in_code_tool_id && (rule.ids?.includes(tool.in_code_tool_id) ?? false)) ||
    (!!tool.name && (rule.names?.includes(tool.name) ?? false)) ||
    (!!display && (rule.displayIncludes?.some((s) => display.includes(s)) ?? false))
  );
}

export function getIconForAction(tool: ToolSnapshot): IconComponent {
  for (const rule of ACTION_ICON_RULES) {
    if (matchesRule(tool, rule)) return rule.icon;
  }
  return SvgCpu;
}
