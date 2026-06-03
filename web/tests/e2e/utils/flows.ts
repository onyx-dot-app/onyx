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

/** How long to let the Celery worker pick the run up and finish it. */
const RUN_TIMEOUT_MS = 60_000;

export interface SeededRun {
  flowId: string;
  runId: string;
}

interface FlowNodeSeed {
  id: string;
  name: string;
  kind: "HTTP" | "TRANSFORM" | "CONDITION" | "AI";
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
      transform("seed", "Collect rows", { rows: "{{ trigger.rows }}" }, {
        next: ["check"],
      }),
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

async function expectOk(
  label: string,
  send: () => Promise<{ ok: () => boolean; status: () => number; text: () => Promise<string> }>
): Promise<void> {
  const res = await send();
  if (!res.ok()) {
    throw new Error(`${label} failed: ${res.status()} ${await res.text()}`);
  }
}

/**
 * Create, publish and run a flow, then wait for the run to finish.
 *
 * Returns the ids so a spec can navigate straight to the run view.
 */
export async function seedFinishedRun(
  request: APIRequestContext,
  name: string
): Promise<SeededRun> {
  const createRes = await request.post("/api/flows", {
    data: { name, description: "Seeded for the run view", spec: inspectableFlowSpec() },
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
    throw new Error(`starting the run failed: ${runRes.status()} ${await runRes.text()}`);
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
