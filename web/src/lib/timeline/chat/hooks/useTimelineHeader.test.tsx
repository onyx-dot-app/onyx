import { renderHook } from "@testing-library/react";
import { Packet, PacketType } from "@/app/app/services/streamingModels";
import { TurnGroup } from "@/lib/timeline/chat/transformers";
import { useTimelineHeader } from "@/lib/timeline/chat/hooks/useTimelineHeader";

jest.mock("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string, values?: Record<string, string>) =>
    values ? `${key}:${Object.values(values).join(",")}` : key,
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

  it("shows working until a rendered packet arrives", () => {
    const { result } = renderHook(() => useTimelineHeader(group([debug])));
    expect(result.current.headerText).toBe("header.working.label");
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

  it("names a step by the tool whose arguments stream first", () => {
    const delta = (toolType: string): Packet => ({
      placement: { turn_index: 0 },
      obj: {
        type: PacketType.TOOL_CALL_ARGUMENT_DELTA,
        tool_type: toolType,
        tool_id: "call",
        argument_deltas: {},
      },
    });
    const { result, rerender } = renderHook(
      ({ packets }: { packets: Packet[] }) => useTimelineHeader(group(packets)),
      {
        initialProps: {
          packets: [
            delta("python"),
            {
              placement: { turn_index: 0 },
              obj: { type: PacketType.PYTHON_TOOL_START, code: "print(1)" },
            },
          ],
        },
      }
    );
    expect(result.current.headerText).toBe("header.executingCode.label");

    rerender({ packets: [delta("generate_image")] });
    expect(result.current.headerText).toBe("header.generatingImages.label");
  });

  it("names the program a command runs", () => {
    const { result } = renderHook(() =>
      useTimelineHeader(
        group([
          {
            placement: { turn_index: 0 },
            obj: {
              type: PacketType.EXEC_COMMAND_START,
              cmd: "npm test",
              workdir: null,
            },
          },
        ])
      )
    );
    expect(result.current.headerText).toBe("header.runningProgram.label:npm");
  });

  it("previews the latest reasoning on one line", () => {
    const reasoning = (text: string): Packet => ({
      placement: { turn_index: 0 },
      obj: { type: PacketType.REASONING_DELTA, reasoning: text },
    });
    const start: Packet = {
      placement: { turn_index: 0 },
      obj: { type: PacketType.REASONING_START },
    };
    const { result, rerender } = renderHook(
      ({ packets }: { packets: Packet[] }) => useTimelineHeader(group(packets)),
      { initialProps: { packets: [start] } }
    );
    expect(result.current.headerText).toBe("header.thinking.label");

    rerender({
      packets: [start, reasoning("Check the\n\nlogs "), reasoning(" first.")],
    });
    expect(result.current.headerText).toBe("Check the logs first.");
  });
});
