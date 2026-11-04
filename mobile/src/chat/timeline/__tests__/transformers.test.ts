import { describe, expect, it } from "@jest/globals";

import {
  createInitialState,
  type GroupedPacket,
  processPackets,
} from "@/chat/messageProcessor";
import { type Packet } from "@/chat/streamingModels";
import {
  expandCodeModeSteps,
  groupStepsByTurn,
  transformPacketGroups,
} from "@/chat/timeline/transformers";

const group = (turn_index: number, tab_index: number): GroupedPacket => ({
  turn_index,
  tab_index,
  packets: [],
  nestedCalls: [],
  codeMode: null,
});

describe("transformers", () => {
  it("transforms groups into steps with a turn-tab key", () => {
    const steps = transformPacketGroups([group(0, 0), group(1, 2)]);
    expect(steps.map((s) => s.key)).toEqual(["0-0", "1-2"]);
    expect(steps[0]).toMatchObject({ turnIndex: 0, tabIndex: 0 });
  });

  it("marks a turn parallel when >1 step shares its turn_index", () => {
    const turns = groupStepsByTurn(
      transformPacketGroups([group(0, 0), group(0, 1), group(1, 0)]),
    );
    expect(turns).toHaveLength(2);
    expect(turns[0]).toMatchObject({ turnIndex: 0, isParallel: true });
    expect(turns[0]!.steps.map((s) => s.key)).toEqual(["0-0", "0-1"]);
    expect(turns[1]).toMatchObject({ turnIndex: 1, isParallel: false });
  });

  it("sorts turns ascending and steps by tab_index ascending", () => {
    const turns = groupStepsByTurn(
      transformPacketGroups([
        group(1, 1),
        group(0, 2),
        group(0, 0),
        group(1, 0),
      ]),
    );
    expect(turns.map((t) => t.turnIndex)).toEqual([0, 1]);
    expect(turns[0]!.steps.map((s) => s.tabIndex)).toEqual([0, 2]);
    expect(turns[1]!.steps.map((s) => s.tabIndex)).toEqual([0, 1]);
  });

  describe("code mode", () => {
    const at = (turn: number, sub?: number) => ({
      turn_index: turn,
      tab_index: 0,
      sub_turn_index: sub,
    });
    // An observation of cell 1; the first has no cell id until its end.
    const observation = (
      turn: number,
      body: Packet[],
      ended: boolean,
    ): Packet[] => [
      {
        placement: at(turn),
        obj: {
          type: "code_mode_start",
          code: "",
          cell_id: turn === 0 ? null : 1,
        },
      },
      ...body,
      ...(ended
        ? ([
            {
              placement: at(turn),
              obj: { type: "code_mode_delta", stdout: "", cell_id: 1 },
            },
            { placement: at(turn), obj: { type: "section_end" } },
          ] as Packet[])
        : []),
    ];
    // Steps of a stream, grouped as the message processor groups them.
    const stepsOf = (packets: Packet[]) =>
      transformPacketGroups(
        processPackets(createInitialState(0), packets).toolGroups,
      );
    const search = (turn: number, done: boolean): Packet[] => [
      { placement: at(turn, 0), obj: { type: "search_tool_start" } },
      ...(done
        ? ([
            { placement: at(turn, 0), obj: { type: "section_end" } },
          ] as Packet[])
        : []),
    ];

    it("shows each call once, as a step of its own", () => {
      const { steps } = expandCodeModeSteps(
        stepsOf([
          ...observation(0, search(0, false), true),
          ...observation(1, search(1, true), true),
        ]),
      );
      expect(steps.map((s) => s.key)).toEqual(["0-0-0"]);
      expect(steps[0]!.packets.at(-1)!.obj.type).toBe("section_end");
    });

    it("keeps the fuller report of a running call over a shorter later one", () => {
      const queries = {
        placement: at(0, 0),
        obj: { type: "search_tool_queries_delta", queries: ["onyx"] },
      } as Packet;
      const { steps } = expandCodeModeSteps(
        stepsOf([
          ...observation(0, [...search(0, false), queries], true),
          ...observation(1, search(1, false), true),
        ]),
      );
      expect(steps[0]!.packets.map((p) => p.obj.type)).toEqual([
        "search_tool_start",
        "search_tool_queries_delta",
      ]);
    });

    it("gives a program without calls no step, and works until it returns", () => {
      const running = expandCodeModeSteps(stepsOf(observation(0, [], false)));
      expect(running.steps).toEqual([]);
      expect(running.codeModeWorking).toBe(true);
      const ended = expandCodeModeSteps(stepsOf(observation(0, [], true)));
      expect(ended.codeModeWorking).toBe(false);
    });

    it("does not work while a call carried from an earlier observation runs", () => {
      const { codeModeWorking } = expandCodeModeSteps(
        stepsOf([
          ...observation(0, search(0, false), true),
          ...observation(1, [], false),
        ]),
      );
      expect(codeModeWorking).toBe(false);
    });
  });
});
