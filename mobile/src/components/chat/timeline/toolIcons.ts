// Port of web `toolDisplayHelpers.getToolIcon`, returning the component rather than web's JSX so
// callers control size and colour through `Icon`.
//
// Web falls back to react-icons for two slots, against its own icon rule; mobile substitutes the
// Onyx glyph `chat/tools.ts` already assigns — `FiTool` → `cpu` (its custom-tool fallback),
// `FiList` → `text-lines-small`.
import {
  PacketType,
  type Packet,
  type SearchToolStart,
} from "@/chat/streamingModels";
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

export function getToolIcon(packets: Packet[]): IconFunctionComponent {
  const firstPacket = packets[0];
  if (!firstPacket) return SvgCircle;

  switch (firstPacket.obj.type) {
    case PacketType.SEARCH_TOOL_START:
      // No search-state reducer yet (it lands with the search phase); the start packet already
      // carries the only field this branch reads.
      return (firstPacket.obj as SearchToolStart).is_internet_search
        ? SvgGlobe
        : SvgSearch;
    case PacketType.PYTHON_TOOL_START:
      return SvgTerminalSmall;
    case PacketType.FETCH_TOOL_START:
      return SvgLink;
    case PacketType.CUSTOM_TOOL_START:
      return SvgCpu;
    case PacketType.IMAGE_GENERATION_TOOL_START:
      return SvgImage;
    case PacketType.DEEP_RESEARCH_PLAN_START:
      return SvgTextLinesSmall;
    case PacketType.RESEARCH_AGENT_START:
      return SvgUser;
    case PacketType.CODING_AGENT_START:
      return SvgCode;
    case PacketType.REASONING_START:
      return SvgSlowTime;
    case PacketType.MEMORY_TOOL_START:
    case PacketType.MEMORY_TOOL_NO_ACCESS:
      return SvgBookOpen;
    default:
      return SvgCircle;
  }
}
