import { renderHook } from "@testing-library/react";
import { Packet, PacketType } from "@/app/app/services/streamingModels";
import { TurnGroup } from "@/app/app/message/messageComponents/timeline/transformers";
import { useTimelineHeader } from "@/app/app/message/messageComponents/timeline/hooks/useTimelineHeader";

jest.mock("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string, values?: { toolName?: string }) =>
    values?.toolName ? `${key}:${values.toolName}` : key,
}));

const debug: Packet = {
  placement: { turn_index: 0 },
  obj: {
    type: PacketType.TOOL_CALL_DEBUG,
    tool_call_id: "call",
    tool_name: "lookup",
    tool_args: {},
  },
};

function group(packets: Packet[]): TurnGroup[] {
  return [
    {
      turnIndex: 0,
      isParallel: false,
      steps: [
        {
          key: "0-0",
          groupKey: "0-0",
          turnIndex: 0,
          tabIndex: 0,
          packets,
          nestedCalls: [],
          streamPackets: packets,
          codeMode: null,
        },
      ],
    },
  ];
}

describe("useTimelineHeader", () => {
  it("uses the tool name when debug precedes the tool start", () => {
    const { result } = renderHook(() =>
      useTimelineHeader(
        group([
          debug,
          {
            placement: { turn_index: 0 },
            obj: {
              type: PacketType.CUSTOM_TOOL_START,
              tool_name: "Lookup",
              display_name: "Lookup",
            },
          },
        ])
      )
    );
    expect(result.current.headerText).toBe(
      "header.executingNamedTool.label:Lookup"
    );
  });

  it("names a qualified external tool by its display name", () => {
    const { result } = renderHook(() =>
      useTimelineHeader(
        group([
          {
            placement: { turn_index: 0 },
            obj: {
              type: PacketType.CUSTOM_TOOL_START,
              tool_name: "mcp__3__my__srv__create_issue",
              display_name: "create_issue",
            },
          },
        ])
      )
    );
    expect(result.current.headerText).toBe(
      "header.executingNamedTool.label:create_issue"
    );
  });

  it("keeps the pending header until a rendered packet arrives", () => {
    const { result } = renderHook(() => useTimelineHeader(group([debug])));
    expect(result.current.headerText).toBe("header.thinkingEllipsis.label");
  });

  it("shows image generation as an ordinary step", () => {
    const { result } = renderHook(() =>
      useTimelineHeader(
        group([
          {
            placement: { turn_index: 0 },
            obj: { type: PacketType.IMAGE_GENERATION_TOOL_START },
          },
        ])
      )
    );
    expect(result.current.headerText).toBe("header.generatingImages.label");
  });

  it("reads work without a step as working", () => {
    const { result } = renderHook(() =>
      useTimelineHeader(
        group([
          {
            placement: { turn_index: 0 },
            obj: { type: PacketType.SEARCH_TOOL_START },
          },
          {
            placement: { turn_index: 0 },
            obj: { type: PacketType.SECTION_END },
          },
        ]),
        undefined,
        true
      )
    );
    expect(result.current.headerText).toBe("header.working.label");
  });
});
