/**
 * Immutable edits to a flow spec.
 *
 * The editor holds the spec in state and replaces it wholesale on every
 * change, so these helpers never mutate what they are given. Keeping them
 * pure also means the fiddly parts — repointing edges around a deleted node,
 * choosing a fresh id — are testable without a browser.
 */

import { successorsOf } from "@/app/flows/graphLayout";
import type {
  AiNode,
  CodeNode,
  ConditionNode,
  DelayNode,
  FilterNode,
  MergeNode,
  FlowNode,
  FlowNodeKind,
  FlowSpec,
  HttpNode,
  HumanNode,
  LoopNode,
  RetryNode,
  ScheduleNode,
  TransformNode,
  WebhookNode,
} from "@/app/flows/types";

const DEFAULT_RETRY = { max_attempts: 1, backoff_seconds: 1 };

/** Replace one node, leaving everything else identical. */
export function updateNode(
  spec: FlowSpec,
  nodeId: string,
  replacement: FlowNode
): FlowSpec {
  return {
    ...spec,
    nodes: spec.nodes.map((node) => (node.id === nodeId ? replacement : node)),
  };
}

/**
 * A node id that is free in this spec.
 *
 * Ids are referenced from other nodes and from run history, so they follow
 * the server's rule: lowercase, digits and underscores, starting with a
 * letter.
 */
export function nextNodeId(spec: FlowSpec, kind: FlowNodeKind): string {
  const base = kind.toLowerCase();
  const taken = new Set(spec.nodes.map((node) => node.id));
  if (!taken.has(base)) return base;

  let suffix = 2;
  while (taken.has(`${base}_${suffix}`)) suffix += 1;
  return `${base}_${suffix}`;
}

/** A node of the given kind, with defaults that pass server validation. */
export function blankNode(id: string, kind: FlowNodeKind): FlowNode {
  const base = {
    id,
    name: id,
    next: [],
    for_each: null,
    on_error: "stop" as const,
    retry: { ...DEFAULT_RETRY },
  };

  switch (kind) {
    case "HTTP": {
      const node: HttpNode = {
        ...base,
        kind: "HTTP",
        method: "GET",
        url: "https://",
        headers: {},
        query: {},
        body: null,
        timeout_seconds: 30,
        result_path: null,
        fail_on_error_status: true,
      };
      return node;
    }
    case "TRANSFORM": {
      const node: TransformNode = {
        ...base,
        kind: "TRANSFORM",
        fields: { value: "" },
      };
      return node;
    }
    case "CONDITION": {
      const node: ConditionNode = {
        ...base,
        kind: "CONDITION",
        left: "",
        operator: "eq",
        right: "",
        on_true: [],
        on_false: [],
      };
      return node;
    }
    case "AI": {
      const node: AiNode = {
        ...base,
        kind: "AI",
        prompt: "",
        output_fields: [],
        timeout_seconds: 90,
      };
      return node;
    }
    case "HUMAN": {
      const node: HumanNode = {
        ...base,
        kind: "HUMAN",
        question: "",
        assignee: null,
        on_approve: [],
        on_reject: [],
      };
      return node;
    }
    case "CODE": {
      const node: CodeNode = {
        ...base,
        kind: "CODE",
        // A snippet that does nothing is still a valid one, and the comment
        // says more about how the node works than an empty box would.
        code: "result = steps\n",
        timeout_seconds: 30,
      };
      return node;
    }
    case "LOOP": {
      const node: LoopNode = {
        ...base,
        kind: "LOOP",
        over: "",
        batch_size: 10,
      };
      return node;
    }
    case "RETRY": {
      const node: RetryNode = {
        ...base,
        kind: "RETRY",
        method: "GET",
        url: "https://",
        headers: {},
        query: {},
        body: null,
        timeout_seconds: 30,
        result_path: null,
        fail_on_error_status: true,
        until_path: null,
        operator: "eq",
        value: "",
        max_checks: 10,
        interval_seconds: 5,
        fail_when_exhausted: true,
      };
      return node;
    }
    case "DELAY": {
      const node: DelayNode = {
        ...base,
        kind: "DELAY",
        // A minute is the line between sleeping and parking, so the default
        // is the longest wait that costs nothing to set up.
        seconds: 60,
      };
      return node;
    }
    case "FILTER": {
      const node: FilterNode = {
        ...base,
        kind: "FILTER",
        over: "",
        left: "",
        operator: "eq",
        right: "",
      };
      return node;
    }
    case "SCHEDULE": {
      const node: ScheduleNode = {
        ...base,
        kind: "SCHEDULE",
        // Nine on weekday mornings: the shape almost every schedule takes,
        // and obviously wrong if it is not what you meant.
        cron: "0 9 * * 1-5",
      };
      return node;
    }
    case "MERGE": {
      const node: MergeNode = {
        ...base,
        kind: "MERGE",
        // Empty until the author picks them. The server needs two, which is
        // what stops a half-built merge being saved.
        sources: [],
        mode: "combine",
      };
      return node;
    }
    case "WEBHOOK": {
      const node: WebhookNode = {
        ...base,
        kind: "WEBHOOK",
        url: "https://",
        payload: {},
        headers: {},
        timeout_seconds: 30,
        // A receiver being down is their outage, not a reason to stop.
        fail_on_error_status: false,
      };
      return node;
    }
  }
}

/**
 * Append a node, wiring it after `afterNodeId` when one is given.
 *
 * A node added with nothing before it is legal but unreachable, which the
 * canvas shows as a dashed outline rather than hiding.
 */
/** The new spec plus the id of the node just added, for selecting it. */
export interface AddNodeResult {
  spec: FlowSpec;
  nodeId: string;
}

export function addNode(
  spec: FlowSpec,
  kind: FlowNodeKind,
  afterNodeId: string | null
): AddNodeResult {
  const id = nextNodeId(spec, kind);
  const created = blankNode(id, kind);

  const nodes = spec.nodes.map((node) => {
    if (node.id !== afterNodeId) return node;
    // Neither branching kind has a plain `next` in practice, so a node added
    // after one joins the positive branch — the branch people mean when they
    // say "and then".
    if (node.kind === "CONDITION") {
      return { ...node, on_true: [...node.on_true, id] };
    }
    if (node.kind === "HUMAN") {
      return { ...node, on_approve: [...node.on_approve, id] };
    }
    return { ...node, next: [...node.next, id] };
  });

  return { spec: { ...spec, nodes: [...nodes, created] }, nodeId: id };
}

/**
 * Remove a node and heal the graph around it.
 *
 * Anything that pointed at the removed node inherits its successors, so
 * deleting a step from the middle of a chain joins the two ends rather than
 * severing the flow. Branch lists are repaired the same way.
 */
export function removeNode(spec: FlowSpec, nodeId: string): FlowSpec {
  const doomed = spec.nodes.find((node) => node.id === nodeId);
  if (doomed === undefined) return spec;

  const inherited = successorsOf(doomed);
  const repoint = (targets: string[]): string[] => {
    if (!targets.includes(nodeId)) return targets;
    const kept = targets.filter((target) => target !== nodeId);
    // Dedupe: the removed node and its parent may share a successor.
    return [...new Set([...kept, ...inherited])];
  };

  const nodes = spec.nodes
    .filter((node) => node.id !== nodeId)
    .map((node) => {
      if (node.kind === "CONDITION") {
        return {
          ...node,
          next: repoint(node.next),
          on_true: repoint(node.on_true),
          on_false: repoint(node.on_false),
        };
      }
      if (node.kind === "HUMAN") {
        return {
          ...node,
          next: repoint(node.next),
          on_approve: repoint(node.on_approve),
          on_reject: repoint(node.on_reject),
        };
      }
      return { ...node, next: repoint(node.next) };
    });

  // Deleting the entry node promotes whatever it led to, so the spec keeps a
  // valid start. With nothing left to promote the caller gets an empty spec
  // and the page shows its empty state.
  const start =
    spec.start === nodeId ? (inherited[0] ?? nodes[0]?.id ?? "") : spec.start;

  return { ...spec, start, nodes };
}

/** Whether removing this node would leave the spec with nothing to run. */
export function isLastNode(spec: FlowSpec): boolean {
  return spec.nodes.length <= 1;
}

/**
 * Whether two specs describe the same graph.
 *
 * Not `JSON.stringify` equality: the server returns each node's fields in the
 * order its Pydantic model declares them, while a node built here carries the
 * order the object literal used. The two are the same graph, so comparing raw
 * JSON reports a freshly-saved flow as still dirty and the Save button never
 * settles.
 */
export function sameSpec(left: FlowSpec, right: FlowSpec): boolean {
  return canonical(left) === canonical(right);
}

/**
 * A spec serialised with its object keys in a fixed order.
 *
 * `JSON.stringify`'s array replacer both filters and orders keys, so
 * collecting every key first and then passing them sorted gives a stable
 * spelling without dropping anything. Array order is left alone, because in a
 * spec it carries meaning — `next: ["a", "b"]` is not `next: ["b", "a"]`.
 */
function canonical(spec: FlowSpec): string {
  const keys = new Set<string>();
  JSON.stringify(spec, (key, value) => {
    keys.add(key);
    return value;
  });
  return JSON.stringify(spec, [...keys].sort());
}
