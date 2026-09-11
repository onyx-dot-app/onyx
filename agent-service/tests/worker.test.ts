import { expect, test } from "bun:test";
import { AgentWorker } from "../src/worker";

const integration = test.skipIf(!process.env.ONYX_AGENT_TEST_REDIS_URL);
const start = {
  type: "start",
  config: {
    model_provider: "openai",
    model_name: "gpt-5-mini",
    api_key: null,
    api_base: null,
    api_version: null,
    deployment_name: null,
    custom_config: null,
    temperature: 1,
    max_input_tokens: 32000,
    reasoning_effort_default: null,
    reasoning_effort_user_default: null,
    reasoning_effort_max: null,
  },
  apiSurface: null,
  options: {},
  reasoningEffort: "off",
  maxTurns: 2,
  sessionId: null,
  mockResponse: "Queue integration response",
};
async function until(condition: () => boolean) {
  const deadline = Date.now() + 5000;
  while (!condition()) {
    if (Date.now() > deadline) throw new Error("Condition timed out");
    await Bun.sleep(10);
  }
}
function fixture(concurrency = 2, drainTimeoutMs = 3000) {
  const claims = new Set<string>();
  const finishes = new Map<string, string>();
  const callbacks: string[] = [];
  const events: string[] = [];
  const heartbeats: unknown[] = [];
  let running = 0;
  let peak = 0;
  let hold = false;
  let cancel = false;
  let claimFailures = 0;
  const server = Bun.serve({
    port: 0,
    async fetch(request) {
      const streaming = new URL(request.url).pathname.endsWith("events-stream");
      const body = streaming
        ? {
            attemptId: request.headers.get("x-onyx-attempt-id"),
            events: (await request.text())
              .trim()
              .split("\n")
              .flatMap((line) => JSON.parse(line).events),
          }
        : ((await request.json()) as Record<string, unknown>);
      expect(request.headers.get("x-onyx-tenant-id")).toBe("tenant");
      if (new URL(request.url).pathname.endsWith("/heartbeats")) {
        heartbeats.push(body.runs);
        return Response.json({
          cancelled: cancel
            ? (body.runs as { runId: string }[]).map((run) => run.runId)
            : [],
        });
      }
      expect(typeof body.attemptId).toBe("string");
      const parts = new URL(request.url).pathname.split("/");
      const operation = parts.at(-1)!;
      const id = parts.at(-2)!;
      if (operation === "claim") {
        if (claimFailures > 0) {
          claimFailures--;
          return new Response("Temporarily unavailable", { status: 503 });
        }
        if (claims.has(id)) return Response.json({ status: "claimdenied" });
        claims.add(id);
        running++;
        peak = Math.max(peak, running);
        return Response.json({ start });
      }
      if (operation === "heartbeat")
        return Response.json({ cancelled: cancel });
      if (operation === "finish") {
        finishes.set(id, body.status as string);
        running--;
        return Response.json({});
      }
      if (operation === "events" || operation === "events-stream") {
        events.push(
          ...(body.events as { type: string }[]).map((event) => event.type),
        );
        return Response.json({});
      }
      if (operation === "callback") {
        callbacks.push(body.type as string);
        if (body.type === "prepare") {
          while (hold && !request.signal.aborted) await Bun.sleep(10);
          return Response.json({
            value: {
              history: [{ role: "user", content: "hello" }],
              tools: [],
              toolChoice: "none",
            },
          });
        }
        return Response.json({ value: null });
      }
      return new Response("Not found", { status: 404 });
    },
  });
  const worker = new AgentWorker({
    redisUrl: process.env.ONYX_AGENT_TEST_REDIS_URL!,
    apiUrl: server.url.toString().slice(0, -1),
    token: "secret",
    concurrency,
    runTimeoutMs: 5000,
    drainTimeoutMs,
    queueName: `pi-test-${crypto.randomUUID()}`,
  });
  return {
    worker,
    claims,
    finishes,
    events,
    callbacks,
    heartbeats,
    peak: () => peak,
    rejectClaims: (count: number) => {
      claimFailures = count;
    },
    hold: (value: boolean) => {
      hold = value;
    },
    cancel: () => {
      cancel = true;
    },
    async add(id: string) {
      await worker.queue.add("run", { runId: id, tenantId: "tenant" });
    },
    async close() {
      hold = false;
      await worker.close();
      // Use an independent client for cleanup because worker.close closed its Queue.
      const { Queue } = await import("bullmq");
      const { redisConnection } = await import("../src/worker");
      const queue = new Queue(worker.queue.name, {
        connection: redisConnection(process.env.ONYX_AGENT_TEST_REDIS_URL!),
      });
      await queue.obliterate({ force: true });
      await queue.close();
      await server.stop(true);
    },
  };
}

integration(
  "queue workers bound concurrency and duplicate delivery never reexecutes Pi",
  async () => {
    const f = fixture();
    try {
      await f.worker.queue.waitUntilReady();
      f.hold(true);
      await Promise.all([f.add("one"), f.add("two"), f.add("three")]);
      await until(() => f.claims.size === 2);
      expect(f.worker.activeCount).toBe(2);
      expect(await f.worker.metrics()).toContain(
        "onyx_agent_outstanding_runs 3",
      );
      f.hold(false);
      await until(() => f.finishes.size === 3);
      await f.add("one");
      await until(() => f.worker.activeCount === 0);
      await Bun.sleep(100);
      expect(f.peak()).toBe(2);
      expect([...f.finishes.values()]).toEqual([
        "completed",
        "completed",
        "completed",
      ]);
      expect(f.events.filter((event) => event === "done")).toHaveLength(3);
      expect(f.callbacks.filter((event) => event === "prepare")).toHaveLength(
        3,
      );
    } finally {
      await f.close();
    }
  },
);

integration(
  "heartbeat cancellation aborts a blocked callback and finalizes cancellation",
  async () => {
    const f = fixture();
    try {
      await f.worker.queue.waitUntilReady();
      f.hold(true);
      await f.add("cancel");
      await f.add("cancel-two");
      await until(
        () => f.callbacks.filter((type) => type === "prepare").length === 2,
      );
      f.cancel();
      await until(() => f.finishes.has("cancel"));
      await until(() => f.finishes.size === 2);
      expect([...f.finishes.values()]).toEqual(["cancelled", "cancelled"]);
      expect(
        (f.heartbeats[0] as { runId: string }[]).map((run) => run.runId).sort(),
      ).toEqual(["cancel", "cancel-two"]);
    } finally {
      await f.close();
    }
  },
);

integration(
  "draining finishes active runs and leaves queued jobs for another worker",
  async () => {
    const f = fixture(1);
    try {
      await f.worker.queue.waitUntilReady();
      f.hold(true);
      await f.add("active");
      await f.add("waiting");
      await until(() => f.callbacks.includes("prepare"));
      const closed = f.worker.close();
      expect(f.worker.draining).toBe(true);
      expect(await f.worker.ready()).toBe(false);
      await until(() => f.heartbeats.length > 0);
      f.hold(false);
      await closed;
      expect([...f.finishes]).toEqual([["active", "completed"]]);
      expect(f.claims.has("waiting")).toBe(false);
    } finally {
      await f.close();
    }
  },
);

integration(
  "drain deadline interrupts active runs instead of replaying them",
  async () => {
    const f = fixture(1, 50);
    try {
      await f.worker.queue.waitUntilReady();
      f.hold(true);
      await f.add("deadline");
      await until(() => f.callbacks.includes("prepare"));
      await f.worker.close();
      expect(f.finishes.get("deadline")).toBe("interrupted");
    } finally {
      await f.close();
    }
  },
);

integration(
  "official Python producer interoperates with the TypeScript worker",
  async () => {
    const f = fixture();
    try {
      await f.worker.queue.waitUntilReady();
      const child = Bun.spawn(
        [
          process.env.ONYX_AGENT_TEST_PYTHON ?? "../.venv/bin/python",
          "-c",
          `
import asyncio
import os
from bullmq import Queue

async def main():
    queue = Queue(os.environ["PI_TEST_QUEUE"], {"connection": os.environ["ONYX_AGENT_TEST_REDIS_URL"]})
    try:
        await queue.add("run", {"runId": "python-produced", "tenantId": "tenant"}, {"jobId": "python-produced"})
    finally:
        await queue.close()

asyncio.run(main())
`,
        ],
        {
          env: { ...process.env, PI_TEST_QUEUE: f.worker.queue.name },
          stdout: "pipe",
          stderr: "pipe",
        },
      );
      const stderr = await new Response(child.stderr).text();
      expect(await child.exited, stderr).toBe(0);
      await until(() => f.finishes.has("python-produced"));
      expect(f.finishes.get("python-produced")).toBe("completed");
      expect(f.events.at(-1)).toBe("done");
    } finally {
      await f.close();
    }
  },
);

integration(
  "Python reconciliation revives failed delivery while durable claims prevent replay",
  async () => {
    const f = fixture();
    const runId = crypto.randomUUID();
    async function dispatch() {
      const child = Bun.spawn(
        [
          process.env.ONYX_AGENT_TEST_PYTHON ?? "../.venv/bin/python",
          "-c",
          `
import asyncio
import os
from uuid import UUID
from bullmq import Queue
from onyx.chat.pi import dispatch
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

# Each test isolates its queue; exercise the production reconciliation code.
dispatch.Queue = lambda name, opts: Queue(os.environ["PI_TEST_QUEUE"], opts)
CURRENT_TENANT_ID_CONTEXTVAR.set("tenant")
asyncio.run(dispatch.enqueue(UUID(os.environ["PI_TEST_RUN_ID"])))
`,
        ],
        {
          env: {
            ...process.env,
            PYTHONPATH: "../backend",
            ONYX_AGENT_REDIS_URL: process.env.ONYX_AGENT_TEST_REDIS_URL!,
            PI_TEST_QUEUE: f.worker.queue.name,
            PI_TEST_RUN_ID: runId,
          },
          stdout: "pipe",
          stderr: "pipe",
        },
      );
      const stderr = await new Response(child.stderr).text();
      expect(await child.exited, stderr).toBe(0);
    }
    async function waitState(state: string) {
      const deadline = Date.now() + 3000;
      while (
        (await (await f.worker.queue.getJob(runId))?.getState()) !== state
      ) {
        if (Date.now() > deadline)
          throw new Error(`Delivery did not become ${state}`);
        await Bun.sleep(10);
      }
    }
    try {
      await f.worker.queue.waitUntilReady();
      f.rejectClaims(1);
      await dispatch();
      await waitState("failed");
      expect(f.claims.size).toBe(0);
      await dispatch();
      await until(() => f.finishes.has(runId));
      await waitState("completed");
      expect(f.finishes.get(runId)).toBe("completed");
      // Even stale/concurrent reconciliation cannot rerun a durably claimed agent.
      await Promise.all([dispatch(), dispatch()]);
      await waitState("completed");
      expect(f.callbacks.filter((type) => type === "prepare")).toHaveLength(1);
      expect(f.events.filter((type) => type === "done")).toHaveLength(1);
    } finally {
      await f.close();
    }
  },
  30000,
);
