import {
  expandCodeModeSteps,
  groupStepsByTurn,
  transformPacketGroups,
} from "@/app/app/message/messageComponents/timeline/transformers";
import {
  createInitialState,
  processPackets,
} from "@/app/app/message/messageComponents/timeline/hooks/packetProcessor";
import {
  CODE_MODE_TOOL_TYPE,
  Packet,
  PacketType,
} from "@/app/app/services/streamingModels";

// Mobile's chat/timeline/__tests__/transformers.test.ts mirrors these cases;
// keep the two in step.

function at(turn: number, tab = 0, sub?: number) {
  return { turn_index: turn, tab_index: tab, sub_turn_index: sub };
}

function observation(
  turn: number,
  cellId: number | null,
  body: Packet[],
  status?: "running" | "completed"
): Packet[] {
  return [
    {
      placement: at(turn),
      obj: {
        type: PacketType.CODE_MODE_START,
        code: "",
        cell_id: turn === 0 ? null : cellId,
      },
    },
    ...body,
    ...(status
      ? [
          {
            placement: at(turn),
            obj: {
              type: PacketType.CODE_MODE_DELTA,
              stdout: "",
              status,
              cell_id: cellId,
            },
          } as Packet,
          {
            placement: at(turn),
            obj: { type: PacketType.SECTION_END },
          } as Packet,
        ]
      : []),
  ];
}

function search(turn: number, sub: number, done: boolean): Packet[] {
  return [
    {
      placement: at(turn, 0, sub),
      obj: { type: PacketType.SEARCH_TOOL_START },
    },
    ...(done
      ? [
          {
            placement: at(turn, 0, sub),
            obj: { type: PacketType.SECTION_END },
          } as Packet,
        ]
      : []),
  ];
}

/** Timeline steps of a stream, grouped as the packet processor groups them. */
function stepsOf(packets: Packet[]) {
  return transformPacketGroups(
    processPackets(createInitialState(0), packets).toolGroups
  );
}

function expand(packets: Packet[]) {
  return groupStepsByTurn(expandCodeModeSteps(stepsOf(packets)).steps);
}

test("each call of a program is its own step, without the program", () => {
  const turns = expand(
    observation(
      0,
      1,
      [...search(0, 0, true), ...search(0, 1, true)],
      "completed"
    )
  );

  expect(turns.map((turn) => turn.steps.map((step) => step.key))).toEqual([
    ["0-0-0"],
    ["0-0-1"],
  ]);
  for (const turn of turns) {
    expect(turn.isParallel).toBe(false);
    expect(turn.steps[0]!.packets[0]!.obj.type).toBe(
      PacketType.SEARCH_TOOL_START
    );
  }
});

test("a later observation replaces a running call in place", () => {
  const turns = expand([
    ...observation(0, 1, search(0, 0, false), "running"),
    { placement: at(1), obj: { type: PacketType.SEARCH_TOOL_START } },
    { placement: at(1), obj: { type: PacketType.SECTION_END } },
    ...observation(2, 1, search(2, 0, true), "completed"),
  ]);

  expect(turns.map((turn) => turn.steps.map((step) => step.key))).toEqual([
    ["0-0-0"],
    ["1-0"],
  ]);
  const call = turns[0]!.steps[0]!;
  expect(call.groupKey).toBe("2-0");
  expect(call.packets.some((p) => p.obj.type === PacketType.SECTION_END)).toBe(
    true
  );
});

test("a shorter report of a running call keeps the fuller one", () => {
  const queries: Packet = {
    placement: at(0, 0, 0),
    obj: { type: PacketType.SEARCH_TOOL_QUERIES_DELTA, queries: ["onyx"] },
  } as Packet;
  const turns = expand([
    ...observation(0, 1, [...search(0, 0, false), queries], "running"),
    ...observation(1, 1, search(1, 0, false), "running"),
  ]);

  const call = turns[0]!.steps[0]!;
  expect(call.groupKey).toBe("0-0");
  expect(call.packets.map((p) => p.obj.type)).toEqual([
    PacketType.SEARCH_TOOL_START,
    PacketType.SEARCH_TOOL_QUERIES_DELTA,
  ]);
});

test("a program without calls has no step", () => {
  const first = observation(0, 1, [], "running");
  expect(expand([...first, ...observation(1, 1, [])])).toEqual([]);

  const withCall = [...first, ...observation(1, 1, search(1, 0, true))];
  expect(expand(withCall).map((turn) => turn.steps.map((s) => s.key))).toEqual([
    ["0-0-0"],
  ]);
});

test("a program works between calls until it returns", () => {
  const working = (packets: Packet[]) =>
    expandCodeModeSteps(stepsOf(packets)).codeModeWorking;

  expect(working(observation(0, 1, []))).toBe(true);
  expect(working(observation(0, 1, search(0, 0, false)))).toBe(false);
  expect(working(observation(0, 1, search(0, 0, true)))).toBe(true);
  expect(working(observation(0, 1, [], "completed"))).toBe(false);
  // A program that yields runs on, but the model acts next.
  expect(working(observation(0, 1, search(0, 0, true), "running"))).toBe(false);
  // A call carried from an earlier observation is still running.
  expect(
    working([
      ...observation(0, 1, search(0, 0, false), "running"),
      ...observation(1, 1, []),
    ])
  ).toBe(false);
  // The model is still writing the program.
  expect(
    working([
      {
        placement: at(0),
        obj: {
          type: PacketType.TOOL_CALL_ARGUMENT_DELTA,
          tool_type: CODE_MODE_TOOL_TYPE,
          tool_id: "call-1",
          argument_deltas: { code: "x = 1" },
        },
      } as Packet,
    ])
  ).toBe(false);
  // A program with a direct sibling after it in the same turn.
  expect(
    working([
      ...observation(0, 1, search(0, 0, true)),
      ...search(0, 0, true).map((p) => ({ ...p, placement: at(0, 1) })),
    ])
  ).toBe(true);
});

test("steps keep their keys and objects when an earlier cell gains a call", () => {
  const first = [
    ...observation(0, 1, search(0, 0, true)),
    ...search(0, 0, true).map((p) => ({ ...p, placement: at(0, 1) })),
  ];
  let state = processPackets(createInitialState(0), first);
  const before = expandCodeModeSteps(
    transformPacketGroups(state.toolGroups)
  ).steps;
  state = processPackets(state, [...first, ...search(0, 1, true)]);
  const after = expandCodeModeSteps(
    transformPacketGroups(state.toolGroups)
  ).steps;

  expect(before.map((s) => s.key)).toEqual(["0-0-0", "0-1"]);
  // The new call sits with its cell, so the direct step moves; its key does not.
  expect(after.map((s) => s.key)).toEqual(["0-0-0", "0-0-1", "0-1"]);
  // The unchanged call keeps its step object, so memoized renderers skip it.
  expect(after[0]).toBe(before[0]);
});

test("direct parallel calls keep their shared turn", () => {
  const turns = expand([
    ...search(0, 0, true).map((p) => ({ ...p, placement: at(0, 0) })),
    ...search(0, 0, true).map((p) => ({ ...p, placement: at(0, 1) })),
  ]);

  expect(turns).toHaveLength(1);
  expect(turns[0]!.isParallel).toBe(true);
});
