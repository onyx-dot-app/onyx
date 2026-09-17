import { FiCircle, FiList, FiTool } from "react-icons/fi";
import type { useTranslations } from "next-intl";
import { ResponseItem } from "@/app/app/services/streamingModels";
import { constructCurrentSearchState } from "@/app/app/message/messageComponents/timeline/renderers/search/searchStateUtils";
import {
  SvgGlobe,
  SvgSearchMenu,
  SvgTerminal,
  SvgLink,
  SvgImage,
  SvgUser,
  SvgCircle,
  SvgBookOpen,
  SvgSlowTime,
  SvgXCircle,
  SvgCode,
} from "@opal/icons";
import {
  displayType,
  firstTool,
  isComplete,
} from "@/app/app/services/responseItems";

export function hasToolError(items: ResponseItem[]): boolean {
  return items.some((item) => item.content.status === "error");
}

export function isToolComplete(items: ResponseItem[]): boolean {
  const root = items.filter((item) => item.placement.sub_turn_index == null);
  return isComplete(root.length ? root : items);
}

export function getToolErrorIcon(): React.ReactNode {
  return <SvgXCircle className="w-3.5 h-3.5 text-error" />;
}

export function getToolKey(turn_index: number, tab_index: number): string {
  return `${turn_index}-${tab_index}`;
}

export function parseToolKey(key: string): {
  turn_index: number;
  tab_index: number;
} {
  const parts = key.split("-");
  return {
    turn_index: parseInt(parts[0] ?? "0", 10),
    tab_index: parseInt(parts[1] ?? "0", 10),
  };
}

export type TimelineTranslate = ReturnType<
  typeof useTranslations<"chat.messages.timeline">
>;

export function getToolName(
  items: ResponseItem[],
  t: TimelineTranslate
): string {
  const firstItem = items[0];
  if (!firstItem) return t("toolNames.tool");

  switch (displayType(items)) {
    case "web_search":
    case "internal_search": {
      const searchState = constructCurrentSearchState(items);
      return searchState.isInternetSearch
        ? t("toolNames.webSearch")
        : t("toolNames.internalSearch");
    }
    case "run_python":
      return t("toolNames.codeInterpreter");
    case "open_url":
      return t("toolNames.openUrls");
    case "custom":
      return firstTool(items)?.name || t("toolNames.customTool");
    case "generate_image":
      return t("toolNames.generateImage");
    case "plan":
      return t("toolNames.generatePlan");
    case "research_agent":
      return t("toolNames.researchAgent");
    case "coding_agent":
      return t("toolNames.codingAgent");
    case "reasoning":
      return t("toolNames.thinking");
    case "add_memory":
      return t("toolNames.memory");
    default:
      return t("toolNames.tool");
  }
}

export function getToolIcon(items: ResponseItem[]): React.ReactNode {
  const firstItem = items[0];
  if (!firstItem) return <FiCircle className="w-3.5 h-3.5" />;

  switch (displayType(items)) {
    case "web_search":
    case "internal_search": {
      const searchState = constructCurrentSearchState(items);
      return searchState.isInternetSearch ? (
        <SvgGlobe className="w-3.5 h-3.5" />
      ) : (
        <SvgSearchMenu className="w-3.5 h-3.5" />
      );
    }
    case "run_python":
      return <SvgTerminal className="w-3.5 h-3.5" />;
    case "open_url":
      return <SvgLink className="w-3.5 h-3.5" />;
    case "custom":
      return <FiTool className="w-3.5 h-3.5" />;
    case "generate_image":
      return <SvgImage className="w-3.5 h-3.5" />;
    case "plan":
      return <FiList className="w-3.5 h-3.5" />;
    case "research_agent":
      return <SvgUser className="w-3.5 h-3.5" />;
    case "coding_agent":
      return <SvgCode className="w-3.5 h-3.5" />;
    case "reasoning":
      return <SvgSlowTime className="w-3.5 h-3.5" />;
    case "add_memory":
      return <SvgBookOpen className="w-3.5 h-3.5" />;
    default:
      return <SvgCircle className="w-3.5 h-3.5" />;
  }
}
