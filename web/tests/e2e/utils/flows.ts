import { type APIRequestContext, expect } from "@playwright/test";

/**
 * Seeding helpers for the Flows run view.
 *
 * Building a graph through the editor is covered by the editor spec. The run
 * view needs a *finished* run with interesting outcomes in it — a skipped
 * branch, a step that fanned out — and the fastest honest way to get one is
 * to create, publish and fire the flow through the API, then drive the view
 * itself through the UI.
 */

/** Statuses a run settles on. */
const TERMINAL_STATUS = /^(SUCCEEDED|FAILED|SKIPPED)$/;

/** The question a seeded parked run asks, once its expressions are resolved. */
export const PARKED_QUESTION = "Send 4 rows in 2 batches?";

/** How long to let the Celery worker pick the run up and finish it. */
const RUN_TIMEOUT_MS = 60_000;

export interface SeededRun {
  flowId: string;
  runId: string;
}

interface FlowNodeSeed {
  id: string;
  name: string;
  kind:
    | "HTTP"
    | "TRANSFORM"
    | "CONDITION"
    | "AI"
    | "HUMAN"
    | "LOOP"
    | "DELAY"
    | "FILTER"
    | "SWITCH"
    | "PARALLEL";
  next: string[];
  for_each: string | null;
  on_error: "stop" | "skip";
  retry: { max_attempts: number; backoff_seconds: number };
  [field: string]: unknown;
}

function transform(
  id: string,
  name: string,
  fields: Record<string, string>,
  options: { next?: string[]; forEach?: string } = {}
): FlowNodeSeed {
  return {
    id,
    name,
    kind: "TRANSFORM",
    next: options.next ?? [],
    for_each: options.forEach ?? null,
    on_error: "stop",
    retry: { max_attempts: 1, backoff_seconds: 1 },
    fields,
  };
}

/**
 * A flow that exercises the run view without leaving the deployment.
 *
 * Every step is a transform, so the run needs no network and no model: the
 * point is the shape of the result, not the work. The condition takes its
 * true branch, which leaves `quiet` skipped, and `expand` fans out over the
 * rows handed in as the trigger payload.
 */
function inspectableFlowSpec() {
  return {
    spec_version: 1,
    start: "seed",
    nodes: [
      transform(
        "seed",
        "Collect rows",
        { rows: "{{ trigger.rows }}" },
        {
          next: ["check"],
        }
      ),
      {
        id: "check",
        name: "Any rows?",
        kind: "CONDITION" as const,
        next: [],
        for_each: null,
        on_error: "stop" as const,
        retry: { max_attempts: 1, backoff_seconds: 1 },
        left: "{{ steps.seed.rows }}",
        operator: "is_not_empty",
        right: null,
        on_true: ["expand"],
        on_false: ["quiet"],
      },
      transform(
        "expand",
        "Label each",
        { label: "issue {{ item.id }}", position: "{{ index }}" },
        { next: ["summary"], forEach: "{{ steps.seed.rows }}" }
      ),
      transform("summary", "Summarise", { labels: "{{ steps.expand }}" }),
      transform("quiet", "Nothing to do", { done: "true" }),
    ],
  };
}

/**
 * A flow that stops on an approval.
 *
 * The loop in front of it is there to give the question something to
 * interpolate: a run parked on "Send 4 rows in 2 batches?" proves the
 * question was rendered against the run rather than copied out of the spec.
 */
function gatedFlowSpec() {
  return {
    spec_version: 1,
    start: "seed",
    nodes: [
      transform(
        "seed",
        "Collect rows",
        { rows: "{{ trigger.rows }}" },
        {
          next: ["chunk"],
        }
      ),
      {
        id: "chunk",
        name: "Batch them",
        kind: "LOOP" as const,
        next: ["gate"],
        for_each: null,
        on_error: "stop" as const,
        retry: { max_attempts: 1, backoff_seconds: 1 },
        over: "{{ steps.seed.rows }}",
        batch_size: 2,
      },
      {
        id: "gate",
        name: "Ask first",
        kind: "HUMAN" as const,
        next: [],
        for_each: null,
        on_error: "stop" as const,
        retry: { max_attempts: 1, backoff_seconds: 1 },
        question:
          "Send {{ steps.chunk.total }} rows in {{ steps.chunk.batch_count }} batches?",
        assignee: null,
        on_approve: ["send"],
        on_reject: [],
      },
      transform(
        "send",
        "Send each batch",
        { batch: "{{ item }}" },
        {
          forEach: "{{ steps.chunk.batches }}",
        }
      ),
    ],
  };
}

/** Long enough to park rather than sleep, and short enough to say so. */
export const PARKED_DELAY_SECONDS = 3600;

/**
 * A flow that filters a list and then waits long enough to park.
 *
 * The filter in front is not decoration: it proves the run got somewhere
 * before parking, which is what the run view has to show.
 */
function delayedFlowSpec() {
  return {
    spec_version: 1,
    start: "keep",
    nodes: [
      {
        id: "keep",
        name: "Keep the open ones",
        kind: "FILTER" as const,
        next: ["wait"],
        for_each: null,
        on_error: "stop" as const,
        retry: { max_attempts: 1, backoff_seconds: 1 },
        over: "{{ trigger.rows }}",
        left: "{{ item.state }}",
        operator: "eq",
        right: "open",
      },
      {
        id: "wait",
        name: "Sleep on it",
        kind: "DELAY" as const,
        next: ["after"],
        for_each: null,
        on_error: "stop" as const,
        retry: { max_attempts: 1, backoff_seconds: 1 },
        seconds: PARKED_DELAY_SECONDS,
      },
      transform("after", "Follow up", { done: "true" }),
    ],
  };
}

async function expectOk(
  label: string,
  send: () => Promise<{
    ok: () => boolean;
    status: () => number;
    text: () => Promise<string>;
  }>
): Promise<void> {
  const res = await send();
  if (!res.ok()) {
    throw new Error(`${label} failed: ${res.status()} ${await res.text()}`);
  }
}

/**
 * Create and fire a flow that parks on an approval, then wait for it to park.
 *
 * Returns once the run is genuinely AWAITING_DECISION, so a spec can open the
 * run view and find the decision panel there rather than racing it.
 */
export async function seedParkedRun(
  request: APIRequestContext,
  name: string
): Promise<SeededRun> {
  const createRes = await request.post("/api/flows", {
    data: {
      name,
      description: "Seeded for the approval view",
      spec: gatedFlowSpec(),
    },
  });
  if (!createRes.ok()) {
    throw new Error(
      `creating the flow failed: ${createRes.status()} ${await createRes.text()}`
    );
  }
  const flow: { id: string } = await createRes.json();

  const runRes = await request.post(`/api/flows/${flow.id}/run?test=true`, {
    data: { payload: { rows: [1, 2, 3, 4] } },
  });
  if (!runRes.ok()) {
    throw new Error(
      `starting the run failed: ${runRes.status()} ${await runRes.text()}`
    );
  }
  const run: { id: string } = await runRes.json();

  await expect
    .poll(
      async () => {
        const res = await request.get(`/api/flows/${flow.id}/runs/${run.id}`);
        if (!res.ok()) return `HTTP ${res.status()}`;
        const body: { status: string } = await res.json();
        return body.status;
      },
      {
        timeout: RUN_TIMEOUT_MS,
        message:
          "the run never parked on its approval — is a worker consuming the scheduled_tasks queue?",
      }
    )
    .toBe("AWAITING_DECISION");

  return { flowId: flow.id, runId: run.id };
}

/**
 * Create, publish and run a flow, then wait for the run to finish.
 *
 * Returns the ids so a spec can navigate straight to the run view.
 */
/**
 * Create and fire a flow that parks on a long delay, then wait for it to park.
 *
 * Nothing here waits out the delay — an hour is the point. The run view has
 * to show what it is waiting for without anybody sitting through it.
 */
export async function seedDelayedRun(
  request: APIRequestContext,
  name: string
): Promise<SeededRun> {
  const createRes = await request.post("/api/flows", {
    data: {
      name,
      description: "Seeded for the delay view",
      spec: delayedFlowSpec(),
    },
  });
  if (!createRes.ok()) {
    throw new Error(
      `creating the flow failed: ${createRes.status()} ${await createRes.text()}`
    );
  }
  const flow: { id: string } = await createRes.json();

  const runRes = await request.post(`/api/flows/${flow.id}/run?test=true`, {
    data: {
      payload: {
        rows: [
          { id: 1, state: "open" },
          { id: 2, state: "closed" },
          { id: 3, state: "open" },
        ],
      },
    },
  });
  if (!runRes.ok()) {
    throw new Error(
      `starting the run failed: ${runRes.status()} ${await runRes.text()}`
    );
  }
  const run: { id: string } = await runRes.json();

  await expect
    .poll(
      async () => {
        const res = await request.get(`/api/flows/${flow.id}/runs/${run.id}`);
        if (!res.ok()) return `HTTP ${res.status()}`;
        const body: { status: string } = await res.json();
        return body.status;
      },
      {
        timeout: RUN_TIMEOUT_MS,
        message:
          "the run never parked on its delay — is a worker consuming the scheduled_tasks queue?",
      }
    )
    .toBe("AWAITING_DELAY");

  return { flowId: flow.id, runId: run.id };
}

export async function seedFinishedRun(
  request: APIRequestContext,
  name: string
): Promise<SeededRun> {
  const createRes = await request.post("/api/flows", {
    data: {
      name,
      description: "Seeded for the run view",
      spec: inspectableFlowSpec(),
    },
  });
  if (!createRes.ok()) {
    throw new Error(
      `creating the flow failed: ${createRes.status()} ${await createRes.text()}`
    );
  }
  const flow: { id: string } = await createRes.json();

  await expectOk("publishing the flow", () =>
    request.post(`/api/flows/${flow.id}/publish`)
  );

  const runRes = await request.post(`/api/flows/${flow.id}/run`, {
    data: { payload: { rows: [{ id: 101 }, { id: 102 }, { id: 103 }] } },
  });
  if (!runRes.ok()) {
    throw new Error(
      `starting the run failed: ${runRes.status()} ${await runRes.text()}`
    );
  }
  const run: { id: string } = await runRes.json();

  await expect
    .poll(
      async () => {
        const res = await request.get(`/api/flows/${flow.id}/runs/${run.id}`);
        if (!res.ok()) return `HTTP ${res.status()}`;
        const body: { status: string } = await res.json();
        return body.status;
      },
      {
        timeout: RUN_TIMEOUT_MS,
        message:
          "the run never reached a terminal status — is a worker consuming the scheduled_tasks queue?",
      }
    )
    .toMatch(TERMINAL_STATUS);

  return { flowId: flow.id, runId: run.id };
}

/** The priority a seeded switch routes on, and the step each one reaches. */
export const SWITCH_ROUTES = {
  high: "page",
  low: "queue",
  otherwise: "triage",
} as const;

/**
 * A switch with a case per priority and a catch-all.
 *
 * Transforms on every branch, so the run needs no network: what is under
 * test is which branch ran and which were skipped.
 */
function switchFlowSpec() {
  return {
    spec_version: 1,
    start: "route",
    nodes: [
      {
        id: "route",
        name: "Route by priority",
        kind: "SWITCH",
        next: [],
        for_each: null,
        on_error: "stop",
        retry: { max_attempts: 1, backoff_seconds: 1 },
        value: "{{ trigger.priority }}",
        cases: [
          { equals: "high", then: [SWITCH_ROUTES.high] },
          { equals: "low", then: [SWITCH_ROUTES.low] },
        ],
        otherwise: [SWITCH_ROUTES.otherwise],
      } satisfies FlowNodeSeed,
      transform(SWITCH_ROUTES.high, "Page on-call", {
        paged: "{{ trigger.priority }}",
      }),
      transform(SWITCH_ROUTES.low, "Queue for later", {
        queued: "{{ trigger.priority }}",
      }),
      transform(SWITCH_ROUTES.otherwise, "Triage", {
        triaged: "{{ trigger.priority }}",
      }),
    ],
  };
}

/**
 * A parallel step aimed at this machine.
 *
 * The SSRF policy refuses loopback, so every call fails before it leaves.
 * That is the point: it is the one outcome that needs no outside endpoint,
 * and it proves the calls ran on the worker, under the tenant's policy, and
 * that the failure names the item it came from.
 */
function parallelFlowSpec() {
  return {
    spec_version: 1,
    start: "lookup",
    nodes: [
      {
        id: "lookup",
        name: "Look up users",
        kind: "PARALLEL",
        next: [],
        for_each: null,
        on_error: "stop",
        retry: { max_attempts: 1, backoff_seconds: 1 },
        method: "GET",
        url: "http://127.0.0.1:9/users/{{ item }}",
        headers: {},
        query: {},
        body: null,
        timeout_seconds: 5,
        result_path: null,
        fail_on_error_status: true,
        over: "{{ trigger.ids }}",
        concurrency: 3,
      } satisfies FlowNodeSeed,
    ],
  };
}

/** Create a flow, fire a test run of it, and wait for the run to settle. */
async function runToTheEnd(
  request: APIRequestContext,
  name: string,
  spec: object,
  payload: object
): Promise<SeededRun> {
  const createRes = await request.post("/api/flows", {
    data: { name, description: "Seeded for the run view", spec },
  });
  if (!createRes.ok()) {
    throw new Error(
      `creating the flow failed: ${createRes.status()} ${await createRes.text()}`
    );
  }
  const flow: { id: string } = await createRes.json();

  const runRes = await request.post(`/api/flows/${flow.id}/run?test=true`, {
    data: { payload },
  });
  if (!runRes.ok()) {
    throw new Error(
      `starting the run failed: ${runRes.status()} ${await runRes.text()}`
    );
  }
  const run: { id: string } = await runRes.json();

  await expect
    .poll(
      async () => {
        const res = await request.get(`/api/flows/${flow.id}/runs/${run.id}`);
        if (!res.ok()) return `HTTP ${res.status()}`;
        const body: { status: string } = await res.json();
        return body.status;
      },
      {
        timeout: RUN_TIMEOUT_MS,
        message:
          "the run never reached a terminal status — is a worker consuming the scheduled_tasks queue?",
      }
    )
    .toMatch(TERMINAL_STATUS);

  return { flowId: flow.id, runId: run.id };
}

export async function seedSwitchRun(
  request: APIRequestContext,
  name: string,
  priority: string
): Promise<SeededRun> {
  return runToTheEnd(request, name, switchFlowSpec(), { priority });
}

export async function seedParallelRun(
  request: APIRequestContext,
  name: string,
  ids: number[]
): Promise<SeededRun> {
  return runToTheEnd(request, name, parallelFlowSpec(), { ids });
}

/** The pause a seeded paced run waits between its batches, in seconds. */
export const PACED_PAUSE_SECONDS = 1;

/**
 * Six rows in batches of two, and a step that sends each batch with a pause
 * between them. Transforms only, so the waiting is the one thing that takes
 * time.
 */
function pacedFlowSpec() {
  return {
    spec_version: 1,
    start: "batch",
    nodes: [
      {
        id: "batch",
        name: "Batch the rows",
        kind: "LOOP",
        next: ["send"],
        for_each: null,
        on_error: "stop",
        retry: { max_attempts: 1, backoff_seconds: 1 },
        over: "{{ trigger.rows }}",
        batch_size: 2,
      } satisfies FlowNodeSeed,
      {
        ...transform(
          "send",
          "Send a batch",
          { sent: "{{ item }}" },
          { forEach: "{{ steps.batch.batches }}" }
        ),
        pause_seconds: PACED_PAUSE_SECONDS,
      },
    ],
  };
}

export async function seedPacedRun(
  request: APIRequestContext,
  name: string
): Promise<SeededRun> {
  return runToTheEnd(request, name, pacedFlowSpec(), {
    rows: [1, 2, 3, 4, 5, 6],
  });
}

interface NodeRunTiming {
  node_id: string;
  item_index: number;
  started_at: string;
  finished_at: string | null;
}

/**
 * Milliseconds from one item of a fan-out finishing to the next starting.
 *
 * Read from the run's rows because they are the only witness to a pause: the
 * page shows what each item produced, not how long the run waited between
 * them.
 */
export async function readItemGapsMs(
  request: APIRequestContext,
  run: SeededRun,
  nodeId: string
): Promise<number[]> {
  const res = await request.get(`/api/flows/${run.flowId}/runs/${run.runId}`);
  if (!res.ok()) {
    throw new Error(`reading the run failed: ${res.status()}`);
  }
  const body: { node_runs: NodeRunTiming[] } = await res.json();
  const rows = body.node_runs
    .filter((row) => row.node_id === nodeId)
    .sort((a, b) => a.item_index - b.item_index);

  return rows.slice(1).map((row, position) => {
    const finished = rows[position]?.finished_at;
    if (finished === null || finished === undefined) {
      throw new Error(`item ${position} of '${nodeId}' never finished`);
    }
    return Date.parse(row.started_at) - Date.parse(finished);
  });
}
