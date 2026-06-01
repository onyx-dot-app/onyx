// Mirrors web actionUtils.ts getIconForAction(). Deviation: OpenURL → SvgExternalLink
// (mobile has no rotated chain-link SvgLink; the external-link glyph is the
// closest curated equivalent).
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

/**
 * One match rule per known tool, in first-match-wins order (web getIconForAction
 * parity). A tool matches if its `in_code_tool_id` is in `ids`, its `name` is in
 * `names`, or its lowercased `display_name` contains any `displayIncludes` entry.
 */
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

/** Return the icon component for a tool/action (web getIconForAction parity). */
export function getIconForAction(tool: ToolSnapshot): IconComponent {
  for (const rule of ACTION_ICON_RULES) {
    if (matchesRule(tool, rule)) return rule.icon;
  }
  return SvgCpu;
}
