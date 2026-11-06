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
      steps: [{ key: "0-0", turnIndex: 0, tabIndex: 0, packets }],
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
            obj: { type: PacketType.CUSTOM_TOOL_START, tool_name: "Lookup" },
          },
        ])
      )
    );
    expect(result.current.headerText).toBe(
      "header.executingNamedTool.label:Lookup"
    );
  });

  it("keeps the pending header until a rendered packet arrives", () => {
    const { result } = renderHook(() => useTimelineHeader(group([debug])));
    expect(result.current.headerText).toBe("header.thinkingEllipsis.label");
  });
});
