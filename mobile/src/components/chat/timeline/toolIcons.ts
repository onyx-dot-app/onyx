// Port of web `toolDisplayHelpers.getToolIcon`, returning the component rather than web's JSX so
// callers control size and colour through `Icon`.
//
// Web falls back to react-icons for two slots, against its own icon rule; mobile substitutes the
// Onyx glyph `chat/tools.ts` already assigns — `FiTool` → `cpu` (its custom-tool fallback),
// `FiList` → `text-lines-small`.
import { ResponseItem } from "@/chat/streamingModels";
import { firstTool } from "@/chat/responseItems";
import SvgBookOpen from "@/icons/book-open";
import SvgCircle from "@/icons/circle";
import SvgCode from "@/icons/code";
import SvgCpu from "@/icons/cpu";
import SvgGlobe from "@/icons/globe";
import SvgImage from "@/icons/image";
import SvgLink from "@/icons/link";
import SvgSearch from "@/icons/search";
import SvgSlowTime from "@/icons/slow-time";
import SvgTerminalSmall from "@/icons/terminal-small";
import SvgTextLinesSmall from "@/icons/text-lines-small";
import SvgUser from "@/icons/user";
import type { IconFunctionComponent } from "@/icons/types";

export function getToolIcon(items: ResponseItem[]): IconFunctionComponent {
  const content = items[0]?.content;
  if (content?.kind === "reasoning") return SvgSlowTime;
  if (content?.kind === "text" && content.purpose === "plan")
    return SvgTextLinesSmall;
  switch (firstTool(items)?.name) {
    case "internal_search":
      return SvgSearch;
    case "web_search":
      return SvgGlobe;
    case "python":
    case "run_python":
      return SvgTerminalSmall;
    case "open_url":
      return SvgLink;
    case "generate_image":
      return SvgImage;
    case "research_agent":
      return SvgUser;
    case "coding_agent":
      return SvgCode;
    case "add_memory":
      return SvgBookOpen;
    default:
      return firstTool(items) ? SvgCpu : SvgCircle;
  }
}
