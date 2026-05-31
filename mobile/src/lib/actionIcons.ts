// Maps a tool/action to its glyph — a 1:1 port of web's
// web/src/app/app/services/actionUtils.ts getIconForAction(). Mobile reuses the
// curated @/components/icons set; the one substitution is OpenURL → SvgExternalLink
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

function isSearchTool(tool: ToolSnapshot): boolean {
  return (
    tool.in_code_tool_id === "SearchTool" ||
    tool.name === "run_search" ||
    !!tool.display_name?.toLowerCase().includes("search tool")
  );
}

function isWebSearchTool(tool: ToolSnapshot): boolean {
  return (
    tool.in_code_tool_id === "WebSearchTool" ||
    !!tool.display_name?.toLowerCase().includes("web_search")
  );
}

function isImageGenerationTool(tool: ToolSnapshot): boolean {
  return (
    tool.in_code_tool_id === "ImageGenerationTool" ||
    !!tool.display_name?.toLowerCase().includes("image generation")
  );
}

function isKnowledgeGraphTool(tool: ToolSnapshot): boolean {
  return (
    tool.in_code_tool_id === "KnowledgeGraphTool" ||
    !!tool.display_name?.toLowerCase().includes("knowledge graph")
  );
}

function isOpenUrlTool(tool: ToolSnapshot): boolean {
  return (
    tool.in_code_tool_id === "OpenURLTool" ||
    tool.name === "open_url" ||
    !!tool.display_name?.toLowerCase().includes("open url")
  );
}

function isCodeInterpreterTool(tool: ToolSnapshot): boolean {
  return (
    tool.in_code_tool_id === "PythonTool" ||
    tool.name === "python" ||
    !!tool.display_name?.toLowerCase().includes("code interpreter")
  );
}

function isCodingAgentTool(tool: ToolSnapshot): boolean {
  return (
    tool.in_code_tool_id === "CodingAgentTool" ||
    tool.name === "coding_agent" ||
    !!tool.display_name?.toLowerCase().includes("coding agent")
  );
}

/** Return the icon component for a tool/action (web getIconForAction parity). */
export function getIconForAction(tool: ToolSnapshot): IconComponent {
  if (isSearchTool(tool)) return SvgSearch;
  if (isWebSearchTool(tool)) return SvgGlobe;
  if (isImageGenerationTool(tool)) return SvgImage;
  if (isKnowledgeGraphTool(tool)) return SvgServer;
  if (isOpenUrlTool(tool)) return SvgExternalLink;
  if (isCodeInterpreterTool(tool)) return SvgTerminal;
  if (isCodingAgentTool(tool)) return SvgCpu;
  return SvgCpu;
}
