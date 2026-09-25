import { describe, expect, it } from "@jest/globals";

import { makePacket } from "@/chat/__tests__/fixtures";
import { PacketType, type ObjTypes } from "@/chat/streamingModels";
import { getToolIcon } from "@/components/chat/timeline/toolIcons";
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
import type { IconFunctionComponent } from "@/icons/types";
import SvgUser from "@/icons/user";

describe("getToolIcon", () => {
  it("splits search on is_internet_search", () => {
    expect(
      getToolIcon([
        makePacket({ type: "search_tool_start", is_internet_search: true }),
      ]),
    ).toBe(SvgGlobe);
    expect(
      getToolIcon([
        makePacket({ type: "search_tool_start", is_internet_search: false }),
      ]),
    ).toBe(SvgSearch);
    // Absent flag reads as an internal search, matching getToolName.
    expect(getToolIcon([makePacket({ type: "search_tool_start" })])).toBe(
      SvgSearch,
    );
  });

  const cases: [PacketType, IconFunctionComponent][] = [
    [PacketType.PYTHON_TOOL_START, SvgTerminalSmall],
    [PacketType.FETCH_TOOL_START, SvgLink],
    [PacketType.CUSTOM_TOOL_START, SvgCpu],
    [PacketType.IMAGE_GENERATION_TOOL_START, SvgImage],
    [PacketType.DEEP_RESEARCH_PLAN_START, SvgTextLinesSmall],
    [PacketType.RESEARCH_AGENT_START, SvgUser],
    [PacketType.CODING_AGENT_START, SvgCode],
    [PacketType.REASONING_START, SvgSlowTime],
    [PacketType.MEMORY_TOOL_START, SvgBookOpen],
    [PacketType.MEMORY_TOOL_NO_ACCESS, SvgBookOpen],
  ];

  it.each(cases)("maps %s", (type, expected) => {
    expect(getToolIcon([makePacket({ type } as ObjTypes)])).toBe(expected);
  });

  it("falls back to the neutral node glyph", () => {
    expect(getToolIcon([])).toBe(SvgCircle);
    expect(getToolIcon([makePacket({ type: "section_end" })])).toBe(SvgCircle);
  });
});
