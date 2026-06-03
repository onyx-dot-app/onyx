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
  updateNode,
} from "@/app/flows/specEdits";
import type {
  ConditionNode,
  FlowNode,
  FlowSpec,
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
