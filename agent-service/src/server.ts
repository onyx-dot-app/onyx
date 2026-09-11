import { z } from "zod";
import { AgentWorker } from "./worker";

const positive = z.coerce.number().int().positive();
const hostname = process.env.ONYX_AGENT_SERVICE_HOST ?? "127.0.0.1";
const token = process.env.ONYX_AGENT_SERVICE_TOKEN;
if (!token?.trim())
  throw new Error(
    "ONYX_AGENT_SERVICE_TOKEN must match the internal API credential",
  );
const runtime = new AgentWorker({
  redisUrl: process.env.ONYX_AGENT_REDIS_URL ?? "redis://127.0.0.1:6381/0",
  apiUrl: (
    process.env.ONYX_AGENT_API_URL ?? "http://127.0.0.1:8080/internal/agent"
  ).replace(/\/$/, ""),
  token,
  eventBatchMs: positive
    .max(1000)
    .parse(process.env.ONYX_AGENT_EVENT_BATCH_MS ?? 200),
  concurrency: positive.parse(process.env.ONYX_AGENT_MAX_CONCURRENT_RUNS ?? 64),
  runTimeoutMs:
    positive
      .max(1800)
      .parse(process.env.ONYX_AGENT_RUN_TIMEOUT_SECONDS ?? 1800) * 1000,
  drainTimeoutMs:
    positive.parse(process.env.ONYX_AGENT_DRAIN_TIMEOUT_SECONDS ?? 1800) * 1000,
});
const server = Bun.serve({
  hostname,
  port: positive.parse(process.env.ONYX_AGENT_SERVICE_PORT ?? 8091),
  async fetch(request) {
    const path = new URL(request.url).pathname;
    if (path === "/health") return Response.json({ status: "ok" });
    try {
      if (path === "/ready") {
        const ready = await runtime.ready();
        return Response.json({ ready }, { status: ready ? 200 : 503 });
      }
      if (path === "/metrics")
        return new Response(
          await Promise.race([
            runtime.metrics(),
            new Promise<never>((_, reject) =>
              setTimeout(() => reject(new Error("Metrics timeout")), 3000),
            ),
          ]),
          { headers: { "Content-Type": "text/plain; version=0.0.4" } },
        );
    } catch {
      return new Response("Unavailable", { status: 503 });
    }
    return new Response("Not found", { status: 404 });
  },
});
console.info(
  `Onyx agent worker listening on ${server.hostname}:${server.port}`,
);
let stopping = false;
for (const signal of ["SIGTERM", "SIGINT"] as const)
  process.on(signal, async () => {
    if (stopping) return;
    stopping = true;
    // Allow processors a final bounded window to persist their interrupted status.
    const hardStop = setTimeout(
      () => process.exit(1),
      runtime.config.drainTimeoutMs + 20_000,
    );
    try {
      await runtime.close();
      await server.stop(true);
      clearTimeout(hardStop);
      process.exit(0);
    } catch {
      process.exit(1);
    }
  });
