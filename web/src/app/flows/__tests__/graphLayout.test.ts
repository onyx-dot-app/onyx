/**
 * Layout is what the canvas draws, so it is worth pinning down: columns must
 * follow the graph, edges must always point forward, and the same spec must
 * lay out the same way twice.
 */

import {
  COLUMN_GAP,
  NODE_WIDTH,
  ancestorsOf,
  branchTargetsOf,
  layoutFlow,
  loopBodiesOf,
  reachableFrom,
  successorsOf,
} from "@/app/flows/graphLayout";
import type {
  ConditionNode,
  FlowNode,
  FlowSpec,
  HumanNode,
  RepeatNode,
  SwitchNode,
  TransformNode,
} from "@/app/flows/types";

function transform(id: string, next: string[] = []): TransformNode {
  return {
    id,
    name: id,
    kind: "TRANSFORM",
    next,
    for_each: null,
    on_error: "stop",
    retry: { max_attempts: 1, backoff_seconds: 1 },
    fields: { value: "1" },
  };
}

function condition(
  id: string,
  onTrue: string[],
  onFalse: string[]
): ConditionNode {
  return {
    id,
    name: id,
    kind: "CONDITION",
    next: [],
    for_each: null,
    on_error: "stop",
    retry: { max_attempts: 1, backoff_seconds: 1 },
    left: "{{ trigger.x }}",
    operator: "eq",
    right: "1",
    on_true: onTrue,
    on_false: onFalse,
  };
}

function human(id: string, onApprove: string[], onReject: string[]): HumanNode {
  return {
    id,
    name: id,
    kind: "HUMAN",
    next: [],
    for_each: null,
    on_error: "stop",
    retry: { max_attempts: 1, backoff_seconds: 1 },
    question: "ok?",
    assignee: null,
    on_approve: onApprove,
    on_reject: onReject,
  };
}

function switchNode(
  id: string,
  cases: Array<[string, string[]]>,
  otherwise: string[] = []
): SwitchNode {
  return {
    id,
    name: id,
    kind: "SWITCH",
    next: [],
    for_each: null,
    on_error: "stop",
    retry: { max_attempts: 1, backoff_seconds: 1 },
    value: "{{ trigger.priority }}",
    cases: cases.map(([equals, then]) => ({ equals, then })),
    otherwise,
  };
}

function repeatNode(
  id: string,
  body: string[],
  next: string[] = []
): RepeatNode {
  return {
    id,
    name: id,
    kind: "REPEAT",
    next,
    for_each: null,
    on_error: "stop",
    retry: { max_attempts: 1, backoff_seconds: 1 },
    body,
    until: "{{ steps.fetch.next }}",
    operator: "is_empty",
    value: null,
    max_passes: 10,
    start: null,
    carry: null,
    collect: null,
    fail_when_exhausted: true,
  };
}

function spec(start: string, nodes: FlowNode[]): FlowSpec {
  return { spec_version: 1, start, nodes };
}

function columnOf(layout: ReturnType<typeof layoutFlow>, id: string): number {
  const found = layout.nodes.find((entry) => entry.node.id === id);
  if (found === undefined) throw new Error(`no node ${id} in layout`);
  return found.column;
}

describe("successorsOf", () => {
  it("includes both branches of a condition", () => {
    expect(successorsOf(condition("c", ["a"], ["b"]))).toEqual(["a", "b"]);
  });

  it("includes both branches of an approval", () => {
    expect(successorsOf(human("g", ["a"], ["b"]))).toEqual(["a", "b"]);
  });

  it("includes every case of a switch and its otherwise", () => {
    const route = switchNode(
      "route",
      [
        ["high", ["page"]],
        ["low", ["queue"]],
      ],
      ["triage"]
    );
    expect(successorsOf(route)).toEqual(["page", "queue", "triage"]);
  });

  it("is just next for every other kind", () => {
    expect(successorsOf(transform("t", ["a", "b"]))).toEqual(["a", "b"]);
  });
});

describe("ancestorsOf", () => {
  it("finds a step two hops back, not just the one before", () => {
    const flow = spec("a", [
      transform("a", ["b"]),
      transform("b", ["c"]),
      transform("c"),
    ]);

    expect(ancestorsOf(flow, "c")).toEqual(["a", "b"]);
  });

  it("follows both sides of a branch", () => {
    const flow = spec("check", [
      condition("check", ["yes"], ["no"]),
      transform("yes", ["join"]),
      transform("no", ["join"]),
      transform("join"),
    ]);

    expect(ancestorsOf(flow, "join")).toEqual(["check", "yes", "no"]);
  });

  it("leaves out a step that does not lead to this one", () => {
    const flow = spec("a", [
      transform("a", ["b"]),
      transform("b"),
      transform("stray"),
    ]);

    expect(ancestorsOf(flow, "b")).toEqual(["a"]);
  });

  it("never offers the step itself", () => {
    const flow = spec("a", [transform("a", ["b"]), transform("b", ["a2"])]);

    expect(ancestorsOf(flow, "a")).not.toContain("a");
  });
});

describe("reachableFrom", () => {
  it("follows both branches", () => {
    const flow = spec("check", [
      condition("check", ["yes"], ["no"]),
      transform("yes"),
      transform("no"),
    ]);
    expect(reachableFrom(flow)).toEqual(new Set(["check", "yes", "no"]));
  });

  it("leaves out what nothing points at", () => {
    const flow = spec("a", [transform("a"), transform("orphan")]);
    expect(reachableFrom(flow)).toEqual(new Set(["a"]));
  });

  it("does not loop forever on a malformed cycle", () => {
    // The server rejects cycles, but the canvas must survive one arriving.
    const flow = spec("a", [transform("a", ["b"]), transform("b", ["a"])]);
    expect(reachableFrom(flow)).toEqual(new Set(["a", "b"]));
  });
});

describe("layoutFlow", () => {
  it("puts a chain in consecutive columns", () => {
    const layout = layoutFlow(
      spec("a", [transform("a", ["b"]), transform("b", ["c"]), transform("c")])
    );

    expect(columnOf(layout, "a")).toBe(0);
    expect(columnOf(layout, "b")).toBe(1);
    expect(columnOf(layout, "c")).toBe(2);
  });

  it("gives a diamond's branches the same column and the join the next", () => {
    const layout = layoutFlow(
      spec("split", [
        transform("split", ["left", "right"]),
        transform("left", ["join"]),
        transform("right", ["join"]),
        transform("join"),
      ])
    );

    expect(columnOf(layout, "left")).toBe(columnOf(layout, "right"));
    expect(columnOf(layout, "join")).toBe(2);
  });

  it("pushes a join past its longest path, not its shortest", () => {
    // `join` must clear `slow`, or the edge from it would run backwards.
    const layout = layoutFlow(
      spec("start", [
        transform("start", ["quick", "slow"]),
        transform("quick", ["join"]),
        transform("slow", ["slower"]),
        transform("slower", ["join"]),
        transform("join"),
      ])
    );

    expect(columnOf(layout, "join")).toBe(3);
  });

  it("never draws an edge that points backwards", () => {
    const layout = layoutFlow(
      spec("start", [
        transform("start", ["a", "b"]),
        transform("a", ["c"]),
        transform("b", ["c"]),
        transform("c", ["d"]),
        transform("d"),
      ])
    );

    for (const edge of layout.edges) {
      // A loop's way round points back on purpose; see the loop tests.
      if (edge.branch === "again") continue;
      expect(columnOf(layout, edge.to)).toBeGreaterThan(
        columnOf(layout, edge.from)
      );
    }
  });

  it("marks branch edges so they can be labelled", () => {
    const layout = layoutFlow(
      spec("check", [
        condition("check", ["yes"], ["no"]),
        transform("yes"),
        transform("no"),
      ])
    );

    const branches = Object.fromEntries(
      layout.edges.map((edge) => [edge.to, edge.branch])
    );
    expect(branches).toEqual({ yes: "true", no: "false" });
  });

  it("marks an approval's branches too", () => {
    const layout = layoutFlow(
      spec("gate", [
        human("gate", ["ship"], ["tell"]),
        transform("ship"),
        transform("tell"),
      ])
    );

    const branches = Object.fromEntries(
      layout.edges.map((edge) => [edge.to, edge.branch])
    );
    expect(branches).toEqual({ ship: "approve", tell: "reject" });
  });

  it("still places a node nothing reaches, and flags it", () => {
    const layout = layoutFlow(spec("a", [transform("a"), transform("orphan")]));

    expect(layout.nodes).toHaveLength(2);
    const orphan = layout.nodes.find((entry) => entry.node.id === "orphan");
    expect(orphan?.reachable).toBe(false);
    expect(layout.nodes.find((entry) => entry.node.id === "a")?.reachable).toBe(
      true
    );
  });

  it("leaves a column gap between neighbours", () => {
    const layout = layoutFlow(
      spec("a", [transform("a", ["b"]), transform("b")])
    );

    const [first, second] = layout.nodes;
    if (first === undefined || second === undefined) {
      throw new Error("expected two placed nodes");
    }
    expect(second.x - (first.x + NODE_WIDTH)).toBe(COLUMN_GAP);
  });

  it("is deterministic", () => {
    const flow = spec("start", [
      transform("start", ["a", "b"]),
      transform("a", ["join"]),
      transform("b", ["join"]),
      transform("join"),
    ]);

    const first = layoutFlow(flow);
    const second = layoutFlow(flow);
    expect(JSON.stringify(first)).toEqual(JSON.stringify(second));
  });

  it("sizes the canvas around its content", () => {
    const layout = layoutFlow(
      spec("a", [transform("a", ["b"]), transform("b")])
    );

    const furthest = Math.max(...layout.nodes.map((n) => n.x + NODE_WIDTH));
    expect(layout.width).toBeGreaterThan(furthest);
    expect(layout.height).toBeGreaterThan(0);
  });

  it("returns an empty layout for an empty spec", () => {
    expect(layoutFlow(spec("a", []))).toEqual({
      nodes: [],
      edges: [],
      width: 0,
      height: 0,
    });
  });

  it("ignores an edge to a node that is not in the spec", () => {
    // Defensive: a truncated payload should not blow up the canvas.
    const layout = layoutFlow(spec("a", [transform("a", ["ghost"])]));
    expect(layout.edges).toHaveLength(0);
    expect(layout.nodes).toHaveLength(1);
  });
});

describe("switch edges", () => {
  it("labels each case with what it matches", () => {
    const layout = layoutFlow(
      spec("route", [
        switchNode(
          "route",
          [
            ["high", ["page"]],
            ["low", ["queue"]],
          ],
          ["triage"]
        ),
        transform("page"),
        transform("queue"),
        transform("triage"),
      ])
    );

    const byTarget = Object.fromEntries(
      layout.edges.map((edge) => [edge.to, [edge.branch, edge.caseLabel]])
    );
    expect(byTarget).toEqual({
      page: ["case", "high"],
      queue: ["case", "low"],
      triage: ["otherwise", null],
    });
  });

  it("draws one edge for two cases that share a step", () => {
    const layout = layoutFlow(
      spec("route", [
        switchNode("route", [
          ["high", ["page"]],
          ["critical", ["page"]],
        ]),
        transform("page"),
      ])
    );

    expect(layout.edges).toHaveLength(1);
    expect(layout.edges[0]?.caseLabel).toBe("high, critical");
  });

  it("cuts a long case short rather than running over the next node", () => {
    const layout = layoutFlow(
      spec("route", [
        switchNode("route", [["{{ steps.owner.body.team_name }}", ["page"]]]),
        transform("page"),
      ])
    );

    const label = layout.edges[0]?.caseLabel ?? "";
    expect(label).toHaveLength(18);
    expect(label.endsWith("…")).toBe(true);
  });
});

describe("branchTargetsOf", () => {
  it("offers what follows and what stands apart, never what came before", () => {
    const flow = spec("fetch", [
      transform("fetch", ["route"]),
      switchNode("route", [["high", ["page"]]]),
      transform("page", ["tell"]),
      transform("tell"),
      transform("loose"),
    ]);

    expect(branchTargetsOf(flow, "route")).toEqual(["page", "tell", "loose"]);
  });
});

describe("loops", () => {
  /** fetch -> tidy repeat; done follows the loop. */
  function paginated(): FlowSpec {
    return spec("pages", [
      repeatNode("pages", ["fetch"], ["done"]),
      transform("fetch", ["tidy"]),
      transform("tidy"),
      transform("done"),
    ]);
  }

  it("counts a loop's body among the steps it can hand control to", () => {
    expect(successorsOf(repeatNode("pages", ["fetch"], ["done"]))).toEqual([
      "done",
      "fetch",
    ]);
  });

  it("finds everything a loop's body leads to", () => {
    expect(loopBodiesOf(paginated())).toEqual(
      new Map([["pages", new Set(["fetch", "tidy"])]])
    );
  });

  it("places the step after a loop after its whole body", () => {
    const layout = layoutFlow(paginated());

    expect(columnOf(layout, "fetch")).toBe(1);
    expect(columnOf(layout, "tidy")).toBe(2);
    // Not column 1, beside the body, where it would read as parallel to it.
    expect(columnOf(layout, "done")).toBe(3);
  });

  it("labels the way in and the way out", () => {
    const layout = layoutFlow(paginated());

    const fromLoop = Object.fromEntries(
      layout.edges
        .filter((edge) => edge.from === "pages")
        .map((edge) => [edge.to, edge.branch])
    );
    expect(fromLoop).toEqual({ fetch: "pass", done: "after" });
  });

  it("draws the way round from the end of the body back to the loop", () => {
    const layout = layoutFlow(paginated());

    const again = layout.edges.filter((edge) => edge.branch === "again");
    expect(again.map((edge) => [edge.from, edge.to])).toEqual([
      ["tidy", "pages"],
    ]);
  });

  it("arcs the way out over the body instead of through it", () => {
    const layout = layoutFlow(paginated());
    const out = layout.edges.find((edge) => edge.branch === "after");
    const loopRow = layout.nodes.find((entry) => entry.node.id === "pages");

    expect(out).toBeDefined();
    expect(loopRow).toBeDefined();
    // The label sits above the top of the nodes it joins.
    expect(out?.labelY ?? 0).toBeLessThan(loopRow?.y ?? 0);
  });
});
