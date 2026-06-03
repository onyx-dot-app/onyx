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
    | "FILTER";
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
