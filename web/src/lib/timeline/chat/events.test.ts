import {
  PacketType,
  StopReason,
  type ObjTypes,
  type Packet,
} from "@/app/app/services/streamingModels";
import { chatPacketsToEvents } from "@/lib/timeline/chat/events";
import { reduceTimelineEvents } from "@/lib/timeline/reducer";

function packet(
  obj: ObjTypes,
  turn: number,
  tab = 0,
  sub: number | null = null
): Packet {
  return {
    placement: { turn_index: turn, tab_index: tab, sub_turn_index: sub },
    obj,
  };
}

function sectionEnd(turn: number, tab = 0, sub: number | null = null): Packet {
  return packet({ type: PacketType.SECTION_END }, turn, tab, sub);
}

function stop(reason: StopReason): Packet {
  return packet({ type: PacketType.STOP, stop_reason: reason }, 0);
}

function summary(packets: Packet[]) {
  return reduceTimelineEvents(chatPacketsToEvents(packets)).entries.map(
    (entry) => {
      const { payload } = entry;
      return [
        entry.id,
        entry.status,
        payload.kind === "tool"
          ? (payload.toolCall._meta?.onyx?.toolType ?? "")
          : payload.kind,
      ];
    }
  );
}

describe("chatPacketsToEvents", () => {
  it("maps reasoning, a tool step and the answer, in arrival order", () => {
    const packets = [
      packet({ type: PacketType.REASONING_START }, 0),
      packet(
        { type: PacketType.REASONING_DELTA, reasoning: "Let me look." },
        0
      ),
      sectionEnd(0),
      packet(
        { type: PacketType.SEARCH_TOOL_START, is_internet_search: false },
        1
      ),
      packet(
        { type: PacketType.SEARCH_TOOL_QUERIES_DELTA, queries: ["timeline"] },
        1
      ),
      sectionEnd(1),
      packet(
        {
          type: PacketType.MESSAGE_START,
          id: "m",
          content: "",
          final_documents: null,
        },
        2
      ),
      packet({ type: PacketType.MESSAGE_DELTA, content: "Done." }, 2),
      stop(StopReason.FINISHED),
    ];

    expect(summary(packets)).toEqual([
      ["part:think:0-0", "done", "thinking"],
      ["tc:1-0", "done", "internal_search"],
      ["part:msg:2-0", "done", "message"],
    ]);
    expect(reduceTimelineEvents(chatPacketsToEvents(packets)).stopReason).toBe(
      "end_turn"
    );
  });

  it("keeps parallel tools as separate entries, without tabs", () => {
    const packets = [
      packet({ type: PacketType.SEARCH_TOOL_START }, 0, 0),
      packet(
        { type: PacketType.SEARCH_TOOL_START, is_internet_search: true },
        0,
        1
      ),
      sectionEnd(0, 0),
    ];

    expect(summary(packets)).toEqual([
      ["tc:0-0", "done", "internal_search"],
      ["tc:0-1", "streaming", "web_search"],
    ]);
  });

  it("ends calls left open when a later turn starts", () => {
    expect(
      summary([
        packet({ type: PacketType.FETCH_TOOL_START }, 0),
        packet({ type: PacketType.MESSAGE_DELTA, content: "Hi" }, 1),
      ])
    ).toEqual([
      ["tc:0-0", "done", "open_url"],
      ["part:msg:1-0", "streaming", "message"],
    ]);
  });

  it("marks a failed tool and cancels open calls on a user stop", () => {
    const packets = [
      packet({ type: PacketType.PYTHON_TOOL_START, code: "1/0" }, 0, 0),
      packet({ type: PacketType.ERROR }, 0, 0),
      packet({ type: PacketType.MEMORY_TOOL_START }, 0, 1),
      stop(StopReason.USER_CANCELLED),
    ];
    const state = reduceTimelineEvents(chatPacketsToEvents(packets));

    expect(summary(packets)).toEqual([
      ["tc:0-0", "error", "python"],
      ["tc:0-1", "stopped", "memory"],
    ]);
    expect(state.stopReason).toBe("cancelled");
  });

  it("shows a timeout as its own notice, not as another stop reason", () => {
    const state = reduceTimelineEvents(
      chatPacketsToEvents([
        packet({ type: PacketType.MESSAGE_DELTA, content: "Partial" }, 0),
        stop(StopReason.TIMED_OUT),
      ])
    );

    expect(state.stopReason).toBeNull();
    expect(state.entries.at(-1)?.payload).toEqual({
      kind: "notice",
      notice: { type: "timed_out" },
    });
  });

  it("starts streamed Python code once, before its start packet", () => {
    expect(
      summary([
        packet(
          {
            type: PacketType.TOOL_CALL_ARGUMENT_DELTA,
            tool_type: "run_python",
            tool_id: "",
            argument_deltas: { code: "print(" },
          },
          0
        ),
        packet({ type: PacketType.PYTHON_TOOL_START, code: "print(1)" }, 0),
      ])
    ).toEqual([["tc:0-0", "streaming", "python"]]);
  });

  it("leaves an agent's nested calls for its own page", () => {
    expect(
      summary([
        packet(
          { type: PacketType.RESEARCH_AGENT_START, research_task: "Find" },
          0
        ),
        packet({ type: PacketType.SEARCH_TOOL_START }, 0, 0, 0),
        packet({ type: PacketType.REASONING_DELTA, reasoning: "x" }, 0, 0, 1),
      ])
    ).toEqual([["tc:0-0", "streaming", "research_agent"]]);
  });

  it("shows a code mode program's nested calls as steps, not the program", () => {
    expect(
      summary([
        packet({ type: PacketType.CODE_MODE_START, code: "search()" }, 0),
        packet({ type: PacketType.SEARCH_TOOL_START }, 0, 0, 0),
        sectionEnd(0, 0, 0),
        packet({ type: PacketType.FETCH_TOOL_START }, 0, 0, 1),
      ])
    ).toEqual([
      ["tc:0-0/0", "done", "internal_search"],
      ["tc:0-0/1", "streaming", "open_url"],
    ]);
  });
});
