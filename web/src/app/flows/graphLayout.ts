/**
 * Turns a flow spec into positioned nodes and edge paths.
 *
 * Named `graphLayout` rather than `layout` because Next reserves `layout.ts`
 * in an app directory for the route's own layout component.
 *
 * The spec stores no coordinates on purpose: positions are derived here, so
 * two people editing the same flow never produce a diff that is only pixels,
 * and the picture can never drift from the graph it claims to show. The cost
 * is that nodes are not draggable, which for a graph this size is a fair
 * trade.
 *
 * Layered left-to-right, the usual three steps:
 *
 *   1. rank every node by its longest path from a source, which guarantees
 *      each edge spans at least one column
 *   2. order each column by the average row of its predecessors, to keep
 *      edges from crossing more than they must
 *   3. centre the columns against each other so the result looks deliberate
 *
 * Nodes nothing reaches are laid out too. The backend allows them and the
 * editor creates one every time someone adds a node, so hiding them would
 * mean the canvas silently swallowing what you just made.
 */

import type { FlowNode, FlowSpec } from "@/app/flows/types";

export const NODE_WIDTH = 224;
export const NODE_HEIGHT = 76;
export const COLUMN_GAP = 96;
export const ROW_GAP = 32;
export const CANVAS_PADDING = 48;

const COLUMN_STRIDE = NODE_WIDTH + COLUMN_GAP;
const ROW_STRIDE = NODE_HEIGHT + ROW_GAP;

/** Which side of a branching node an edge leaves from. */
export type EdgeBranch =
  | "true"
  | "false"
  | "approve"
  | "reject"
  | "case"
  | "otherwise"
  // A loop's three edges: into its body, out when it is done, and the dashed
  // way back from the end of a pass.
  | "pass"
  | "after"
  | "again"
  | null;

/** Longest switch case shown on an edge before it is cut short. */
const MAX_CASE_LABEL_LENGTH = 18;

/**
 * How far a loop's arcs rise above or dip below the nodes they join.
 *
 * Under the canvas padding, so an arc on the top or bottom row stays inside
 * the area the canvas fits to view.
 */
const LOOP_ARC_LIFT = 40;

export interface PositionedNode {
  node: FlowNode;
  x: number;
  y: number;
  column: number;
  row: number;
  /** False when nothing in the graph leads here from the start node. */
  reachable: boolean;
}

export interface PositionedEdge {
  id: string;
  from: string;
  to: string;
  branch: EdgeBranch;
  /** What a switch case matches, shown as typed. Null for every other edge,
   *  whose label is a fixed word the canvas translates. */
  caseLabel: string | null;
  /** SVG cubic path: right edge to left edge, or an arc for a loop. */
  path: string;
  labelX: number;
  labelY: number;
  /** Where the edge meets the target, for the arrow dot. */
  endX: number;
  endY: number;
}

export interface FlowLayout {
  nodes: PositionedNode[];
  edges: PositionedEdge[];
  width: number;
  height: number;
}

/** Every node this one can hand control to, branches included. */
export function successorsOf(node: FlowNode): string[] {
  if (node.kind === "CONDITION") {
    return [...node.next, ...node.on_true, ...node.on_false];
  }
  if (node.kind === "HUMAN") {
    return [...node.next, ...node.on_approve, ...node.on_reject];
  }
  if (node.kind === "SWITCH") {
    const cases = node.cases.flatMap((branch) => branch.then);
    return [...node.next, ...cases, ...node.otherwise];
  }
  if (node.kind === "REPEAT") {
    return [...node.next, ...node.body];
  }
  return [...node.next];
}

/**
 * Each loop's own steps: everything its body leads to.
 *
 * Mirrors `_body_of` in `backend/onyx/flows/models.py`, which is what the
 * server runs once per pass.
 */
export function loopBodiesOf(spec: FlowSpec): Map<string, Set<string>> {
  const byId = new Map(spec.nodes.map((node) => [node.id, node]));
  const bodies = new Map<string, Set<string>>();

  for (const node of spec.nodes) {
    if (node.kind !== "REPEAT") continue;
    const inside = new Set<string>();
    const stack = [...node.body];
    while (stack.length > 0) {
      const current = stack.pop();
      if (current === undefined || inside.has(current)) continue;
      const found = byId.get(current);
      if (found === undefined) continue;
      inside.add(current);
      stack.push(...successorsOf(found));
    }
    bodies.set(node.id, inside);
  }
  return bodies;
}

/**
 * Successors for placing nodes, which is not quite the graph.
 *
 * A loop's `next` runs after its body, not beside it, so every step in the
 * body is treated as leading there too. Without that, the step after a loop
 * lands in the same column as the loop's first step and reads as parallel.
 */
function placementSuccessors(spec: FlowSpec): Map<string, string[]> {
  const placement = new Map(
    spec.nodes.map((node) => [node.id, successorsOf(node)])
  );
  const bodies = loopBodiesOf(spec);

  for (const node of spec.nodes) {
    if (node.kind !== "REPEAT") continue;
    const inside = bodies.get(node.id) ?? new Set<string>();
    const after = node.next.filter((target) => !inside.has(target));
    for (const id of inside) {
      placement.get(id)?.push(...after);
    }
  }
  return placement;
}

/** Which branch an edge represents, for labelling and colour. */
function branchOf(node: FlowNode, target: string): EdgeBranch {
  if (node.kind === "CONDITION") {
    if (node.on_true.includes(target)) return "true";
    if (node.on_false.includes(target)) return "false";
    return null;
  }
  if (node.kind === "HUMAN") {
    if (node.on_approve.includes(target)) return "approve";
    if (node.on_reject.includes(target)) return "reject";
    return null;
  }
  if (node.kind === "SWITCH") {
    if (node.cases.some((branch) => branch.then.includes(target))) {
      return "case";
    }
    if (node.otherwise.includes(target)) return "otherwise";
    return null;
  }
  if (node.kind === "REPEAT") {
    if (node.body.includes(target)) return "pass";
    if (node.next.includes(target)) return "after";
    return null;
  }
  return null;
}

/**
 * The values of every switch case that leads to ``target``.
 *
 * Two cases may share a step — "high" and "critical" both paging someone is
 * ordinary — and one edge labelled with both reads better than two edges
 * drawn on top of each other.
 */
function caseLabelOf(node: FlowNode, target: string): string | null {
  if (node.kind !== "SWITCH") return null;
  const matched = node.cases
    .filter((branch) => branch.then.includes(target))
    .map((branch) => branch.equals.trim());
  if (matched.length === 0) return null;

  const label = matched.join(", ");
  return label.length > MAX_CASE_LABEL_LENGTH
    ? `${label.slice(0, MAX_CASE_LABEL_LENGTH - 1)}…`
    : label;
}

/**
 * Steps a branch of ``nodeId`` may lead to.
 *
 * Everything except the node itself and the steps before it. Pointing at
 * either would close a loop, which the server refuses, so the switch's
 * pickers never offer one.
 */
export function branchTargetsOf(spec: FlowSpec, nodeId: string): string[] {
  const before = new Set(ancestorsOf(spec, nodeId));
  return spec.nodes
    .filter((node) => node.id !== nodeId && !before.has(node.id))
    .map((node) => node.id);
}

/**
 * Steps that lead to ``nodeId``, in the order the spec declares them.
 *
 * What a merge is allowed to name as a source: the server rejects anything
 * else, so the editor offers exactly this rather than letting somebody pick a
 * step that has not run and finding out on save.
 */
export function ancestorsOf(spec: FlowSpec, nodeId: string): string[] {
  const byId = new Map(spec.nodes.map((node) => [node.id, node]));

  const leadsTo = (from: string): boolean => {
    const seen = new Set<string>();
    const start = byId.get(from);
    const stack = start === undefined ? [] : successorsOf(start);
    while (stack.length > 0) {
      const current = stack.pop();
      if (current === undefined || seen.has(current)) continue;
      seen.add(current);
      if (current === nodeId) return true;
      const node = byId.get(current);
      if (node !== undefined) stack.push(...successorsOf(node));
    }
    return false;
  };

  return spec.nodes
    .filter((node) => node.id !== nodeId && leadsTo(node.id))
    .map((node) => node.id);
}

export function reachableFrom(spec: FlowSpec): Set<string> {
  const byId = new Map(spec.nodes.map((node) => [node.id, node]));
  const seen = new Set<string>();
  const stack = [spec.start];

  while (stack.length > 0) {
    const current = stack.pop();
    if (current === undefined || seen.has(current)) continue;
    const node = byId.get(current);
    if (node === undefined) continue;
    seen.add(current);
    stack.push(...successorsOf(node));
  }
  return seen;
}

/**
 * Nodes in an order where every node follows its predecessors.
 *
 * Kahn's algorithm, seeded in declaration order so a spec always lays out the
 * same way. A cycle would strand nodes here; the server rejects those before
 * a spec can be saved, and any stragglers are appended so nothing vanishes
 * from the canvas over a bad payload.
 */
function topologicalOrder(
  spec: FlowSpec,
  placement: Map<string, string[]>
): FlowNode[] {
  const byId = new Map(spec.nodes.map((node) => [node.id, node]));
  const indegree = new Map(spec.nodes.map((node) => [node.id, 0]));

  for (const node of spec.nodes) {
    for (const target of placement.get(node.id) ?? []) {
      const current = indegree.get(target);
      if (current !== undefined) indegree.set(target, current + 1);
    }
  }

  const ready = spec.nodes.filter((node) => indegree.get(node.id) === 0);
  const ordered: FlowNode[] = [];

  while (ready.length > 0) {
    const node = ready.shift();
    if (node === undefined) break;
    ordered.push(node);
    for (const target of placement.get(node.id) ?? []) {
      const remaining = indegree.get(target);
      if (remaining === undefined) continue;
      indegree.set(target, remaining - 1);
      if (remaining - 1 === 0) {
        const next = byId.get(target);
        if (next !== undefined) ready.push(next);
      }
    }
  }

  if (ordered.length < spec.nodes.length) {
    const placed = new Set(ordered.map((node) => node.id));
    ordered.push(...spec.nodes.filter((node) => !placed.has(node.id)));
  }
  return ordered;
}

/** Longest path from a source, which is the node's column. */
function assignColumns(
  ordered: FlowNode[],
  placement: Map<string, string[]>
): Map<string, number> {
  const column = new Map(ordered.map((node) => [node.id, 0]));

  for (const node of ordered) {
    const here = column.get(node.id) ?? 0;
    for (const target of placement.get(node.id) ?? []) {
      const existing = column.get(target);
      if (existing !== undefined && existing < here + 1) {
        column.set(target, here + 1);
      }
    }
  }
  return column;
}

/**
 * Order each column so edges cross as little as they reasonably can.
 *
 * One barycentre pass: a node sits at the average row of the nodes pointing
 * at it. Left to right, so each column is ordered against rows that are
 * already settled. Ties keep declaration order, which is what stops the
 * layout jumping around between renders.
 */
function assignRows(
  ordered: FlowNode[],
  column: Map<string, number>,
  placement: Map<string, string[]>
): Map<string, number> {
  const predecessors = new Map<string, string[]>();
  for (const node of ordered) {
    for (const target of placement.get(node.id) ?? []) {
      const existing = predecessors.get(target);
      if (existing === undefined) predecessors.set(target, [node.id]);
      else existing.push(node.id);
    }
  }

  const columns = new Map<number, FlowNode[]>();
  for (const node of ordered) {
    const index = column.get(node.id) ?? 0;
    const bucket = columns.get(index);
    if (bucket === undefined) columns.set(index, [node]);
    else bucket.push(node);
  }

  const row = new Map<string, number>();
  const declarationIndex = new Map(
    ordered.map((node, index) => [node.id, index])
  );

  for (const index of [...columns.keys()].sort((a, b) => a - b)) {
    const bucket = columns.get(index) ?? [];
    const weighted = bucket.map((node) => {
      const parents = predecessors.get(node.id) ?? [];
      const rows = parents
        .map((parent) => row.get(parent))
        .filter((value): value is number => value !== undefined);
      const barycentre =
        rows.length > 0
          ? rows.reduce((sum, value) => sum + value, 0) / rows.length
          : Number.POSITIVE_INFINITY;
      return { node, barycentre };
    });

    weighted.sort((a, b) => {
      if (a.barycentre !== b.barycentre) return a.barycentre - b.barycentre;
      return (
        (declarationIndex.get(a.node.id) ?? 0) -
        (declarationIndex.get(b.node.id) ?? 0)
      );
    });

    weighted.forEach((entry, position) => row.set(entry.node.id, position));
  }
  return row;
}

/** A cubic that leaves the source horizontally and arrives the same way. */
function edgePath(
  fromX: number,
  fromY: number,
  toX: number,
  toY: number
): string {
  // A control offset proportional to the gap keeps short hops from bulging
  // and long ones from looking like a straight line with a kink.
  const reach = Math.max(COLUMN_GAP * 0.6, Math.abs(toX - fromX) * 0.4);
  return `M ${fromX} ${fromY} C ${fromX + reach} ${fromY} ${toX - reach} ${toY} ${toX} ${toY}`;
}

interface EdgeGeometry {
  path: string;
  labelX: number;
  labelY: number;
  endX: number;
  endY: number;
}

function forwardEdge(
  source: PositionedNode,
  target: PositionedNode
): EdgeGeometry {
  const fromX = source.x + NODE_WIDTH;
  const fromY = source.y + NODE_HEIGHT / 2;
  const toX = target.x;
  const toY = target.y + NODE_HEIGHT / 2;
  return {
    path: edgePath(fromX, fromY, toX, toY),
    labelX: (fromX + toX) / 2,
    labelY: (fromY + toY) / 2,
    endX: toX,
    endY: toY,
  };
}

/**
 * Top edge to top edge, over whatever sits between.
 *
 * A loop's way out goes this way. Drawn straight, it would run through the
 * body, which sits in the columns between the loop and what follows it.
 */
function arcOver(source: PositionedNode, target: PositionedNode): EdgeGeometry {
  return arc(
    source.x + NODE_WIDTH / 2,
    source.y,
    target.x + NODE_WIDTH / 2,
    target.y,
    -LOOP_ARC_LIFT
  );
}

/** Bottom edge to bottom edge: the way back into a loop. */
function arcUnder(
  source: PositionedNode,
  target: PositionedNode
): EdgeGeometry {
  return arc(
    source.x + NODE_WIDTH / 2,
    source.y + NODE_HEIGHT,
    target.x + NODE_WIDTH / 2,
    target.y + NODE_HEIGHT,
    LOOP_ARC_LIFT
  );
}

function arc(
  fromX: number,
  fromY: number,
  toX: number,
  toY: number,
  lift: number
): EdgeGeometry {
  // A cubic reaches three quarters of its control offset, so this peaks at
  // `lift` away from the nodes it joins.
  const reach = (lift * 4) / 3;
  return {
    path: `M ${fromX} ${fromY} C ${fromX} ${fromY + reach} ${toX} ${toY + reach} ${toX} ${toY}`,
    labelX: (fromX + toX) / 2,
    labelY: (fromY + toY) / 2 + lift,
    endX: toX,
    endY: toY,
  };
}

export function layoutFlow(spec: FlowSpec): FlowLayout {
  if (spec.nodes.length === 0) {
    return { nodes: [], edges: [], width: 0, height: 0 };
  }

  const placement = placementSuccessors(spec);
  const ordered = topologicalOrder(spec, placement);
  const column = assignColumns(ordered, placement);
  const row = assignRows(ordered, column, placement);
  const reachable = reachableFrom(spec);

  // Centre every column against the tallest one so the graph reads as a band
  // rather than a staircase pinned to the top edge.
  const heightOfColumn = new Map<number, number>();
  for (const node of ordered) {
    const index = column.get(node.id) ?? 0;
    heightOfColumn.set(index, (heightOfColumn.get(index) ?? 0) + 1);
  }
  const tallest = Math.max(...heightOfColumn.values());

  const positioned: PositionedNode[] = ordered.map((node) => {
    const columnIndex = column.get(node.id) ?? 0;
    const rowIndex = row.get(node.id) ?? 0;
    const offset = (tallest - (heightOfColumn.get(columnIndex) ?? 1)) / 2;
    return {
      node,
      column: columnIndex,
      row: rowIndex,
      x: CANVAS_PADDING + columnIndex * COLUMN_STRIDE,
      y: CANVAS_PADDING + (rowIndex + offset) * ROW_STRIDE,
      reachable: reachable.has(node.id),
    };
  });

  const positionById = new Map(
    positioned.map((entry) => [entry.node.id, entry])
  );

  const edges: PositionedEdge[] = [];
  for (const source of positioned) {
    // One edge per pair, however many branches of the source lead there.
    for (const targetId of new Set(successorsOf(source.node))) {
      const target = positionById.get(targetId);
      if (target === undefined) continue;

      const branch = branchOf(source.node, targetId);
      edges.push({
        id: `${source.node.id}->${targetId}`,
        from: source.node.id,
        to: targetId,
        branch,
        caseLabel: caseLabelOf(source.node, targetId),
        ...(branch === "after"
          ? arcOver(source, target)
          : forwardEdge(source, target)),
      });
    }
  }

  // The way back from the end of a pass: from each step in a loop's body
  // that leads nowhere else, round underneath to the loop.
  for (const [loopId, inside] of loopBodiesOf(spec)) {
    const loop = positionById.get(loopId);
    if (loop === undefined) continue;
    for (const id of inside) {
      const exit = positionById.get(id);
      if (exit === undefined || successorsOf(exit.node).length > 0) continue;
      edges.push({
        id: `${id}->${loopId}:again`,
        from: id,
        to: loopId,
        branch: "again",
        caseLabel: null,
        ...arcUnder(exit, loop),
      });
    }
  }

  const width =
    Math.max(...positioned.map((entry) => entry.x + NODE_WIDTH)) +
    CANVAS_PADDING;
  const height =
    Math.max(...positioned.map((entry) => entry.y + NODE_HEIGHT)) +
    CANVAS_PADDING;

  return { nodes: positioned, edges, width, height };
}
