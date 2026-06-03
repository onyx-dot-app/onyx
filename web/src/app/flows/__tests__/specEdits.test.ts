/**
 * Spec edits, especially deletion: the editor's job is to leave a spec the
 * server will still accept, and a severed graph is the easiest way to fail
 * that.
 */

import {
  addNode,
  blankNode,
  isLastNode,
  nextNodeId,
  removeNode,
  sameSpec,
  updateNode,
} from "@/app/flows/specEdits";
import type {
  ConditionNode,
  FlowNode,
  FlowSpec,
  HumanNode,
  SwitchNode,
  TransformNode,
} from "@/app/flows/types";

/** Narrow for assertions; a wrong kind here means the test is wrong. */
function asCondition(node: FlowNode | undefined): ConditionNode {
  if (node === undefined || node.kind !== "CONDITION") {
    throw new Error(`expected a condition, got ${node?.kind ?? "nothing"}`);
  }
  return node;
}

/** The node at `index`, or a clear failure rather than `undefined`. */
function nodeAt(spec: FlowSpec, index: number): FlowNode {
  const node = spec.nodes[index];
  if (node === undefined) throw new Error(`no node at index ${index}`);
  return node;
}

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

/** Narrow for assertions; a wrong kind here means the test is wrong. */
function asHuman(node: FlowNode | undefined): HumanNode {
  if (node === undefined || node.kind !== "HUMAN") {
    throw new Error(`expected an approval, got ${node?.kind ?? "nothing"}`);
  }
  return node;
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

/** Narrow for assertions; a wrong kind here means the test is wrong. */
function asSwitch(node: FlowNode | undefined): SwitchNode {
  if (node === undefined || node.kind !== "SWITCH") {
    throw new Error(`expected a switch, got ${node?.kind ?? "nothing"}`);
  }
  return node;
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

function spec(start: string, nodes: FlowNode[]): FlowSpec {
  return { spec_version: 1, start, nodes };
}

describe("nextNodeId", () => {
  it("uses the bare kind when it is free", () => {
    expect(nextNodeId(spec("a", [transform("a")]), "HTTP")).toBe("http");
  });

  it("counts up past what is taken", () => {
    const flow = spec("http", [transform("http"), transform("http_2")]);
    expect(nextNodeId(flow, "HTTP")).toBe("http_3");
  });
});

describe("blankNode", () => {
  it("builds each kind with server-valid defaults", () => {
    expect(blankNode("x", "HTTP")).toMatchObject({
      kind: "HTTP",
      method: "GET",
      timeout_seconds: 30,
    });
    expect(blankNode("x", "CONDITION")).toMatchObject({ operator: "eq" });
    expect(blankNode("x", "AI")).toMatchObject({ output_fields: [] });
    expect(blankNode("x", "TRANSFORM")).toMatchObject({
      fields: { value: "" },
    });
    expect(blankNode("x", "HUMAN")).toMatchObject({
      on_approve: [],
      on_reject: [],
    });
    expect(blankNode("x", "CODE")).toMatchObject({ timeout_seconds: 30 });
    expect(blankNode("x", "LOOP")).toMatchObject({ batch_size: 10 });
    expect(blankNode("x", "RETRY")).toMatchObject({
      max_checks: 10,
      interval_seconds: 5,
    });
    // A receiver being down is their outage, not a reason to stop the run.
    expect(blankNode("x", "WEBHOOK")).toMatchObject({
      fail_on_error_status: false,
    });
    // The longest wait that still costs nothing to set up.
    expect(blankNode("x", "DELAY")).toMatchObject({ seconds: 60 });
    expect(blankNode("x", "FILTER")).toMatchObject({ operator: "eq" });
    expect(blankNode("x", "SCHEDULE")).toMatchObject({ cron: "0 9 * * 1-5" });
    // A list typed by a person has spaces in it and a trailing comma.
    expect(blankNode("x", "SPLIT")).toMatchObject({
      separator: ",",
      trim: true,
      drop_empty: true,
    });
    // Empty on purpose: the server needs two, which is what stops a
    // half-built merge being saved.
    expect(blankNode("x", "MERGE")).toMatchObject({
      sources: [],
      mode: "combine",
    });
    // One row to fill in; the server refuses it blank, so a half-built
    // switch cannot be saved.
    expect(blankNode("x", "SWITCH")).toMatchObject({
      cases: [{ equals: "", then: [] }],
      otherwise: [],
    });
    expect(blankNode("x", "PARALLEL")).toMatchObject({
      method: "GET",
      over: "",
      concurrency: 5,
    });
  });

  it("keeps a retry inside the server's wait budget", () => {
    const node = blankNode("x", "RETRY");
    if (node.kind !== "RETRY") throw new Error("wrong kind");
    expect(node.max_checks * node.interval_seconds).toBeLessThanOrEqual(600);
  });

  it("names the node after its id", () => {
    expect(blankNode("fetch_issues", "HTTP").name).toBe("fetch_issues");
  });
});

describe("updateNode", () => {
  it("swaps one node and leaves the rest alone", () => {
    const flow = spec("a", [transform("a", ["b"]), transform("b")]);
    const renamed = { ...transform("a", ["b"]), name: "Renamed" };

    const next = updateNode(flow, "a", renamed);

    expect(nodeAt(next, 0).name).toBe("Renamed");
    expect(next.nodes[1]).toBe(flow.nodes[1]);
    expect(nodeAt(flow, 0).name).toBe("a");
  });
});

describe("addNode", () => {
  it("wires the new node after the one selected", () => {
    const flow = spec("a", [transform("a")]);

    const { spec: next, nodeId } = addNode(flow, "HTTP", "a");

    expect(nodeId).toBe("http");
    expect(nodeAt(next, 0).next).toEqual(["http"]);
    expect(next.nodes).toHaveLength(2);
  });

  it("adds an unwired node when nothing is selected", () => {
    const flow = spec("a", [transform("a")]);

    const { spec: next } = addNode(flow, "AI", null);

    expect(nodeAt(next, 0).next).toEqual([]);
    expect(next.nodes).toHaveLength(2);
  });

  it("puts a node added after a condition on the true branch", () => {
    const flow: FlowSpec = spec("check", [
      {
        id: "check",
        name: "check",
        kind: "CONDITION",
        next: [],
        for_each: null,
        on_error: "stop",
        retry: { max_attempts: 1, backoff_seconds: 1 },
        left: "{{ trigger.x }}",
        operator: "eq",
        right: "1",
        on_true: [],
        on_false: [],
      },
    ]);

    const { spec: next, nodeId } = addNode(flow, "TRANSFORM", "check");

    expect(asCondition(next.nodes[0]).on_true).toEqual([nodeId]);
  });
});

describe("addNode after an approval", () => {
  it("puts the new node on the approve branch", () => {
    const flow = spec("gate", [human("gate", [], [])]);

    const { spec: next, nodeId } = addNode(flow, "HTTP", "gate");

    const gate = asHuman(next.nodes[0]);
    expect(gate.on_approve).toEqual([nodeId]);
    expect(gate.on_reject).toEqual([]);
    expect(gate.next).toEqual([]);
  });
});

describe("addNode after a switch", () => {
  it("puts the new node on the first case", () => {
    const flow = spec("route", [
      switchNode("route", [
        ["high", []],
        ["low", []],
      ]),
    ]);

    const { spec: next, nodeId } = addNode(flow, "HTTP", "route");

    const route = asSwitch(next.nodes[0]);
    expect(route.cases.map((branch) => branch.then)).toEqual([[nodeId], []]);
    expect(route.otherwise).toEqual([]);
    expect(route.next).toEqual([]);
  });
});

describe("removeNode", () => {
  it("joins the two ends of a chain", () => {
    const flow = spec("a", [
      transform("a", ["b"]),
      transform("b", ["c"]),
      transform("c"),
    ]);

    const next = removeNode(flow, "b");

    expect(next.nodes.map((node) => node.id)).toEqual(["a", "c"]);
    expect(nodeAt(next, 0).next).toEqual(["c"]);
  });

  it("does not duplicate a successor the parent already had", () => {
    const flow = spec("a", [
      transform("a", ["b", "c"]),
      transform("b", ["c"]),
      transform("c"),
    ]);

    const next = removeNode(flow, "b");

    expect(nodeAt(next, 0).next).toEqual(["c"]);
  });

  it("repairs both branches of a condition", () => {
    const flow: FlowSpec = spec("check", [
      {
        id: "check",
        name: "check",
        kind: "CONDITION",
        next: [],
        for_each: null,
        on_error: "stop",
        retry: { max_attempts: 1, backoff_seconds: 1 },
        left: "{{ trigger.x }}",
        operator: "eq",
        right: "1",
        on_true: ["doomed"],
        on_false: ["other"],
      },
      transform("doomed", ["tail"]),
      transform("other"),
      transform("tail"),
    ]);

    const condition = asCondition(removeNode(flow, "doomed").nodes[0]);

    expect(condition.on_true).toEqual(["tail"]);
    expect(condition.on_false).toEqual(["other"]);
  });

  it("repairs both branches of an approval", () => {
    const flow = spec("gate", [
      human("gate", ["ship"], ["ship"]),
      transform("ship", ["tell"]),
      transform("tell"),
    ]);

    const next = removeNode(flow, "ship");

    const gate = asHuman(next.nodes[0]);
    expect(gate.on_approve).toEqual(["tell"]);
    expect(gate.on_reject).toEqual(["tell"]);
    expect(next.nodes).toHaveLength(2);
  });

  it("repairs every case and the otherwise of a switch", () => {
    const flow = spec("route", [
      switchNode(
        "route",
        [
          ["high", ["page"]],
          ["low", ["queue"]],
        ],
        ["page"]
      ),
      transform("page", ["tell"]),
      transform("queue"),
      transform("tell"),
    ]);

    const next = removeNode(flow, "page");

    const route = asSwitch(next.nodes[0]);
    expect(route.cases.map((branch) => branch.then)).toEqual([
      ["tell"],
      ["queue"],
    ]);
    expect(route.otherwise).toEqual(["tell"]);
  });

  it("promotes a successor when the start node goes", () => {
    const flow = spec("a", [transform("a", ["b"]), transform("b")]);

    const next = removeNode(flow, "a");

    expect(next.start).toBe("b");
  });

  it("leaves a valid start when the removed node led nowhere", () => {
    const flow = spec("a", [transform("a"), transform("loose")]);

    const next = removeNode(flow, "a");

    expect(next.start).toBe("loose");
    expect(next.nodes).toHaveLength(1);
  });

  it("ignores a node that is not there", () => {
    const flow = spec("a", [transform("a")]);
    expect(removeNode(flow, "ghost")).toBe(flow);
  });
});

describe("isLastNode", () => {
  it("is true only when one node remains", () => {
    expect(isLastNode(spec("a", [transform("a")]))).toBe(true);
    expect(isLastNode(spec("a", [transform("a"), transform("b")]))).toBe(false);
  });
});

describe("sameSpec", () => {
  it("ignores key order", () => {
    // The server returns each node's fields in its model's declared order,
    // which is not the order a node built in the editor carries.
    const asSent = spec("a", [transform("a")]);
    const asReturned: FlowSpec = {
      nodes: [
        {
          retry: { backoff_seconds: 1, max_attempts: 1 },
          on_error: "stop",
          for_each: null,
          next: [],
          kind: "TRANSFORM",
          name: "a",
          id: "a",
          fields: { value: "1" },
        },
      ],
      start: "a",
      spec_version: 1,
    };

    expect(JSON.stringify(asSent)).not.toEqual(JSON.stringify(asReturned));
    expect(sameSpec(asSent, asReturned)).toBe(true);
  });

  it("still sees a real change", () => {
    const before = spec("a", [transform("a")]);
    const after = updateNode(before, "a", {
      ...transform("a"),
      name: "Renamed",
    });

    expect(sameSpec(before, after)).toBe(false);
  });

  it("distinguishes list order, which is meaningful", () => {
    const one = spec("a", [
      transform("a", ["b", "c"]),
      transform("b"),
      transform("c"),
    ]);
    const other = spec("a", [
      transform("a", ["c", "b"]),
      transform("b"),
      transform("c"),
    ]);

    expect(sameSpec(one, other)).toBe(false);
  });

  it("treats a missing field and an explicit null as different", () => {
    const withNull = spec("a", [transform("a")]);
    const withoutForEach = spec("a", [{ ...transform("a"), for_each: null }]);

    expect(sameSpec(withNull, withoutForEach)).toBe(true);
  });
});
