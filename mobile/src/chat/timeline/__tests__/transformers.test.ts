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

  // Mirrors web's timeline/transformers.test.ts case for case; keep the two in step.
  describe("code mode", () => {
    const at = (turn: number, tab = 0, sub?: number) => ({
      turn_index: turn,
      tab_index: tab,
      sub_turn_index: sub,
    });
    // An observation of a cell; the first has no cell id until its final delta.
    const observation = (
      turn: number,
      cellId: number,
      body: Packet[],
      status?: "running" | "completed",
    ): Packet[] => [
      {
        placement: at(turn),
        obj: {
          type: "code_mode_start",
          code: "",
          cell_id: turn === 0 ? null : cellId,
        },
      },
      ...body,
      ...(status
        ? ([
            {
              placement: at(turn),
              obj: {
                type: "code_mode_delta",
                stdout: "",
                status,
                cell_id: cellId,
              },
            },
            { placement: at(turn), obj: { type: "section_end" } },
          ] as Packet[])
        : []),
    ];
    const search = (turn: number, sub: number, done: boolean): Packet[] => [
      { placement: at(turn, 0, sub), obj: { type: "search_tool_start" } },
      ...(done
        ? ([
            { placement: at(turn, 0, sub), obj: { type: "section_end" } },
          ] as Packet[])
        : []),
    ];
    const direct = (packets: Packet[], tab: number): Packet[] =>
      packets.map((p) => ({
        ...p,
        placement: at(p.placement.turn_index, tab),
      }));
    // Steps of a stream, grouped as the message processor groups them.
    const stepsOf = (packets: Packet[]) =>
      transformPacketGroups(
        processPackets(createInitialState(0), packets).toolGroups,
      );
    const expand = (packets: Packet[]) =>
      groupStepsByTurn(expandCodeModeSteps(stepsOf(packets)).steps);
    const keys = (packets: Packet[]) =>
      expand(packets).map((turn) => turn.steps.map((step) => step.key));

    it("each call of a program is its own step, without the program", () => {
      const turns = expand(
        observation(
          0,
          1,
          [...search(0, 0, true), ...search(0, 1, true)],
          "completed",
        ),
      );
      expect(turns.map((turn) => turn.steps.map((step) => step.key))).toEqual([
        ["0-0-0"],
        ["0-0-1"],
      ]);
      for (const turn of turns) {
        expect(turn.isParallel).toBe(false);
        expect(turn.steps[0]!.packets[0]!.obj.type).toBe("search_tool_start");
      }
    });

    it("a later observation replaces a running call in place", () => {
      const turns = expand([
        ...observation(0, 1, search(0, 0, false), "running"),
        { placement: at(1), obj: { type: "search_tool_start" } },
        { placement: at(1), obj: { type: "section_end" } },
        ...observation(2, 1, search(2, 0, true), "completed"),
      ]);
      expect(turns.map((turn) => turn.steps.map((step) => step.key))).toEqual([
        ["0-0-0"],
        ["1-0"],
      ]);
      expect(turns[0]!.steps[0]!.packets.at(-1)!.obj.type).toBe("section_end");
    });

    it("a shorter report of a running call keeps the fuller one", () => {
      const queries = {
        placement: at(0, 0, 0),
        obj: { type: "search_tool_queries_delta", queries: ["onyx"] },
      } as Packet;
      const turns = expand([
        ...observation(0, 1, [...search(0, 0, false), queries], "running"),
        ...observation(1, 1, search(1, 0, false), "running"),
      ]);
      expect(turns[0]!.steps[0]!.packets.map((p) => p.obj.type)).toEqual([
        "search_tool_start",
        "search_tool_queries_delta",
      ]);
    });

    it("a program without calls has no step", () => {
      const first = observation(0, 1, [], "running");
      expect(expand([...first, ...observation(1, 1, [])])).toEqual([]);
      expect(
        keys([...first, ...observation(1, 1, search(1, 0, true))]),
      ).toEqual([["0-0-0"]]);
    });

    it("a program works between calls until it returns", () => {
      const working = (packets: Packet[]) =>
        expandCodeModeSteps(stepsOf(packets)).codeModeWorking;

      expect(working(observation(0, 1, []))).toBe(true);
      expect(working(observation(0, 1, search(0, 0, false)))).toBe(false);
      expect(working(observation(0, 1, search(0, 0, true)))).toBe(true);
      expect(working(observation(0, 1, [], "completed"))).toBe(false);
      // A program that yields runs on, but the model acts next.
      expect(working(observation(0, 1, search(0, 0, true), "running"))).toBe(
        false,
      );
      // A call carried from an earlier observation is still running.
      expect(
        working([
          ...observation(0, 1, search(0, 0, false), "running"),
          ...observation(1, 1, []),
        ]),
      ).toBe(false);
      // The model is still writing the program.
      expect(
        working([
          {
            placement: at(0),
            obj: {
              type: "tool_call_argument_delta",
              tool_type: "execute_code",
              tool_id: "call-1",
              argument_deltas: { code: "x = 1" },
            },
          } as Packet,
        ]),
      ).toBe(false);
      // A program with a direct sibling after it in the same turn.
      expect(
        working([
          ...observation(0, 1, search(0, 0, true)),
          ...direct(search(0, 0, true), 1),
        ]),
      ).toBe(true);
    });

    it("steps keep their keys when an earlier cell gains a call", () => {
      const first = [
        ...observation(0, 1, search(0, 0, true)),
        ...direct(search(0, 0, true), 1),
      ];
      let state = processPackets(createInitialState(0), first);
      const before = expandCodeModeSteps(
        transformPacketGroups(state.toolGroups),
      ).steps;
      state = processPackets(state, [...first, ...search(0, 1, true)]);
      const after = expandCodeModeSteps(
        transformPacketGroups(state.toolGroups),
      ).steps;

      expect(before.map((s) => s.key)).toEqual(["0-0-0", "0-1"]);
      // The new call sits with its cell, so the direct step moves; its key does not.
      expect(after.map((s) => s.key)).toEqual(["0-0-0", "0-0-1", "0-1"]);
    });

    it("direct parallel calls keep their shared turn", () => {
      const turns = expand([
        ...direct(search(0, 0, true), 0),
        ...direct(search(0, 0, true), 1),
      ]);
      expect(turns).toHaveLength(1);
      expect(turns[0]!.isParallel).toBe(true);
    });
  });
});
