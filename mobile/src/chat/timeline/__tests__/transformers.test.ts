import { describe, expect, it } from "@jest/globals";

import { type GroupedItem } from "@/chat/messageProcessor";
import {
  groupStepsByTurn,
  transformItemGroups,
} from "@/chat/timeline/transformers";

const group = (turn_index: number, tab_index: number): GroupedItem => ({
  turn_index,
  tab_index,
  items: [],
});

describe("transformers", () => {
  it("transforms groups into steps with a turn-tab key", () => {
    const steps = transformItemGroups([group(0, 0), group(1, 2)]);
    expect(steps.map((s) => s.key)).toEqual(["0-0", "1-2"]);
    expect(steps[0]).toMatchObject({ turnIndex: 0, tabIndex: 0 });
  });

  it("marks a turn parallel when >1 step shares its turn_index", () => {
    const turns = groupStepsByTurn(
      transformItemGroups([group(0, 0), group(0, 1), group(1, 0)]),
    );
    expect(turns).toHaveLength(2);
    expect(turns[0]).toMatchObject({ turnIndex: 0, isParallel: true });
    expect(turns[0]!.steps.map((s) => s.key)).toEqual(["0-0", "0-1"]);
    expect(turns[1]).toMatchObject({ turnIndex: 1, isParallel: false });
  });

  it("sorts turns ascending and steps by tab_index ascending", () => {
    const turns = groupStepsByTurn(
      transformItemGroups([group(1, 1), group(0, 2), group(0, 0), group(1, 0)]),
    );
    expect(turns.map((t) => t.turnIndex)).toEqual([0, 1]);
    expect(turns[0]!.steps.map((s) => s.tabIndex)).toEqual([0, 2]);
    expect(turns[1]!.steps.map((s) => s.tabIndex)).toEqual([0, 1]);
  });
});
