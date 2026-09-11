import { Queue, Worker, type ConnectionOptions } from "bullmq";
import { z } from "zod";
import { startSchema } from "./protocol";
import { ChatRun } from "./run";
import { HttpHost, RunApi } from "./host";
import { ModelFailure } from "./errors";
import { heartbeatBatch, type RunLease } from "./heartbeats";

const jobSchema = z
  .object({ runId: z.string().min(1), tenantId: z.string().min(1) })
  .strict();
type Status = "completed" | "failed" | "cancelled" | "interrupted";
export interface WorkerConfig {
  redisUrl: string;
  apiUrl: string;
  token: string;
  concurrency: number;
  runTimeoutMs: number;
  drainTimeoutMs: number;
  queueName?: string;
  eventBatchMs?: number;
}

export function redisConnection(url: string): ConnectionOptions {
  const parsed = new URL(url);
  if (!["redis:", "rediss:"].includes(parsed.protocol))
    throw new Error("Invalid agent Redis URL");
  const db = z.coerce
    .number()
    .int()
    .nonnegative()
    .parse(parsed.pathname.slice(1) || 0);
  return {
    host: parsed.hostname,
    port: Number(parsed.port || 6379),
    username: parsed.username ? decodeURIComponent(parsed.username) : undefined,
    password: parsed.password ? decodeURIComponent(parsed.password) : undefined,
    db,
    tls: parsed.protocol === "rediss:" ? {} : undefined,
    maxRetriesPerRequest: null,
    connectTimeout: 5000,
  };
}

/** Queue ownership is delivery only; the API's durable claim authorizes execution. */
export class AgentWorker {
  readonly queue: Queue;
  readonly worker: Worker;
  private active = new Map<
    string,
    RunLease & { tenantId: string; stop(status: Status): void }
  >();
  private heartbeatTimer?: ReturnType<typeof setTimeout>;
  private closed = false;
  private stopping = false;

  constructor(readonly config: WorkerConfig) {
    const connection = redisConnection(config.redisUrl);
    const name = config.queueName ?? "onyx-agent";
    this.queue = new Queue(name, {
      connection: {
        ...connection,
        maxRetriesPerRequest: 1,
        enableOfflineQueue: false,
      },
    });
    this.worker = new Worker(name, (job) => this.execute(job.data), {
      connection,
      concurrency: config.concurrency,
      removeOnComplete: { age: 3600, count: 10000 },
      removeOnFail: { age: 86400, count: 10000 },
    });
    this.worker.on("error", () =>
      console.error("Agent queue connection or worker error"),
    );
    this.worker.on("failed", (job) =>
      console.error("Agent delivery failed", { jobId: job?.id }),
    );
    this.queue.on("error", () =>
      console.error("Agent queue metrics connection error"),
    );
    this.heartbeatTimer = setTimeout(() => this.heartbeat(), 2000);
  }

  get draining() {
    return this.stopping;
  }
  get activeCount() {
    return this.active.size;
  }

  async ready() {
    if (this.stopping || this.worker.backend.connection.status !== "ready")
      return false;
    const client = await this.worker.backend.connection.client;
    return client.status === "ready" && this.worker.isRunning();
  }

  async metrics() {
    if (this.queue.backend.connection.status !== "ready")
      throw new Error("Queue unavailable");
    const client = await this.queue.backend.connection.client;
    if (client.status !== "ready") throw new Error("Queue unavailable");
    const counts = await this.queue.getJobCounts(
      "active",
      "wait",
      "prioritized",
    );
    const outstanding =
      (counts.active ?? 0) + (counts.wait ?? 0) + (counts.prioritized ?? 0);
    return [
      "# HELP onyx_agent_outstanding_runs Global active and runnable queued jobs; aggregate with max, not sum.",
      "# TYPE onyx_agent_outstanding_runs gauge",
      `onyx_agent_outstanding_runs ${outstanding}`,
      "# TYPE onyx_agent_active_runs gauge",
      `onyx_agent_active_runs ${this.active.size}`,
      "# TYPE onyx_agent_capacity gauge",
      `onyx_agent_capacity ${this.config.concurrency}`,
      "# TYPE onyx_agent_draining gauge",
      `onyx_agent_draining ${Number(this.stopping)}`,
      "",
    ].join("\n");
  }

  async close() {
    this.stopping = true;
    const timer = setTimeout(() => {
      for (const run of this.active.values()) run.stop("interrupted");
    }, this.config.drainTimeoutMs);
    try {
      // close stops acquisition but renews active locks until processors finish.
      await this.worker.close();
    } finally {
      clearTimeout(timer);
      this.closed = true;
      clearTimeout(this.heartbeatTimer);
      await this.queue.close();
    }
  }

  private async heartbeat() {
    const groups = new Map<string, Array<RunLease>>();
    for (const run of this.active.values()) {
      const batch = groups.get(run.tenantId) ?? [];
      batch.push({ runId: run.runId, attemptId: run.attemptId });
      groups.set(run.tenantId, batch);
    }
    try {
      await Promise.all(
        [...groups].map(async ([tenantId, runs]) => {
          for (let offset = 0; offset < runs.length; offset += 512) {
            const batch = runs.slice(offset, offset + 512);
            try {
              const cancelled = new Set(
                await heartbeatBatch(
                  this.config.apiUrl,
                  this.config.token,
                  tenantId,
                  batch,
                ),
              );
              for (const run of batch)
                if (cancelled.has(run.runId))
                  this.active.get(run.attemptId)?.stop("cancelled");
            } catch {
              // Losing authority stops execution; a delivery retry must not restart it.
              for (const run of batch)
                this.active.get(run.attemptId)?.stop("interrupted");
            }
          }
        }),
      );
    } finally {
      // One scheduler per worker, including while draining. Requests never overlap.
      if (!this.closed)
        this.heartbeatTimer = setTimeout(() => this.heartbeat(), 2000);
    }
  }

  private async execute(data: unknown) {
    const { runId, tenantId } = jobSchema.parse(data);
    const attemptId = crypto.randomUUID();
    const api = new RunApi(
      this.config.apiUrl,
      this.config.token,
      runId,
      tenantId,
      attemptId,
    );
    const claim = await api.post("claim");
    if (!claim.start) return; // Duplicate/stalled delivery must never replay a claimed run.
    let status: Status = "completed";
    let run: ChatRun | undefined;
    const host = new HttpHost(
      api,
      () => run?.abort(),
      this.config.eventBatchMs,
    );
    let finished = false;
    const stop = (reason: Status) => {
      if (finished || status !== "completed") return;
      status = reason;
      run?.abort();
      host.abort();
    };
    this.active.set(attemptId, { runId, attemptId, tenantId, stop });
    const deadline = setTimeout(
      () => stop("interrupted"),
      this.config.runTimeoutMs,
    );
    let error: Record<string, unknown> | undefined;
    try {
      run = new ChatRun(startSchema.parse(claim.start), host);
      if (this.stopping) stop("interrupted");
      await run.execute();
      await host.flush();
    } catch (cause) {
      if (status === "completed") status = "failed";
      error = {
        message:
          cause instanceof ModelFailure
            ? "Model request failed"
            : "Agent execution interrupted or failed",
        code: cause instanceof ModelFailure ? cause.code : "AGENT_ERROR",
        retryable: cause instanceof ModelFailure ? cause.retryable : false,
      };
    } finally {
      finished = true;
      clearTimeout(deadline);
      host.abort();
      try {
        await api.post("finish", { status, ...(error ? { error } : {}) });
      } finally {
        this.active.delete(attemptId);
      }
    }
  }
}
