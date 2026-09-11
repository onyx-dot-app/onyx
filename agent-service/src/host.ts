import { z } from "zod";
import type { Host } from "./protocol";
import { EventUpload } from "./event_upload";

/** Authenticated, tenant-scoped control plane. Bodies are never logged or retried. */
export class RunApi {
  constructor(
    readonly root: string,
    readonly token: string,
    readonly runId: string,
    readonly tenantId: string,
    readonly attemptId: string,
  ) {}

  post(
    path: string,
    payload: Record<string, unknown> = {},
    signal?: AbortSignal,
  ) {
    const timeout = AbortSignal.timeout(path === "callback" ? 300_000 : 15_000);
    return this.request(
      path,
      JSON.stringify({ attemptId: this.attemptId, ...payload }),
      { "Content-Type": "application/json" },
      signal ? AbortSignal.any([signal, timeout]) : timeout,
    );
  }

  stream(
    sequence: number,
    body: ReadableStream<Uint8Array>,
    signal: AbortSignal,
  ) {
    return this.request(
      "events-stream",
      body,
      {
        "Content-Type": "application/x-ndjson",
        "X-Onyx-Attempt-Id": this.attemptId,
        "X-Onyx-Sequence": String(sequence),
      },
      signal,
    );
  }

  private async request(
    path: string,
    body: string | ReadableStream<Uint8Array>,
    headers: Record<string, string>,
    signal: AbortSignal,
  ) {
    const response = await fetch(
      `${this.root}/runs/${encodeURIComponent(this.runId)}/${path}`,
      {
        method: "POST",
        redirect: "error",
        headers: {
          ...headers,
          Authorization: `Bearer ${this.token}`,
          "X-Onyx-Tenant-Id": this.tenantId,
        },
        body,
        signal,
      },
    );
    if (!response.ok)
      throw new Error(
        `Agent control plane ${path} failed (${response.status})`,
      );
    return z.record(z.string(), z.unknown()).parse(await response.json());
  }
}

/** One ordered upload per model response; callbacks wait for its final checkpoint acknowledgement. */
export class HttpHost implements Host {
  private current?: EventUpload;
  private uploads = new Set<EventUpload>();
  private tail: Promise<unknown> = Promise.resolve();
  private failure?: Error;
  private sequence = 0;
  private readonly controller = new AbortController();

  constructor(
    private readonly api: RunApi,
    private readonly onFailure: () => void,
    private readonly batchIntervalMs = 200,
  ) {}

  send(event: Record<string, unknown>) {
    if (this.failure) throw this.failure;
    if (event.type === "done") {
      this.endUpload();
      this.enqueue(() =>
        this.api.post(
          "events",
          { events: [event], sequence: ++this.sequence },
          this.controller.signal,
        ),
      );
      return;
    }
    try {
      if (!this.current) {
        const upload = new EventUpload(this.batchIntervalMs);
        this.current = upload;
        this.uploads.add(upload);
        this.enqueue(async () => {
          try {
            await this.api.stream(
              ++this.sequence,
              upload.body,
              this.controller.signal,
            );
          } finally {
            upload.abort();
            this.uploads.delete(upload);
          }
        });
      }
      this.current.send(event);
      if (event.type === "model_end") this.endUpload();
    } catch (error) {
      this.abort(
        error instanceof Error ? error : new Error("Agent event upload failed"),
      );
      throw this.failure;
    }
  }

  request(
    type: string,
    payload: Record<string, unknown> = {},
  ): Promise<unknown> {
    this.endUpload();
    return this.enqueue(async () => {
      const result = await this.api.post(
        "callback",
        { type, payload, sequence: ++this.sequence },
        this.controller.signal,
      );
      return result.value;
    });
  }

  async flush() {
    this.endUpload();
    await this.tail;
    if (this.failure) throw this.failure;
  }

  abort(error = new Error("Agent transport aborted")) {
    this.failure ??= error;
    this.controller.abort();
    for (const upload of this.uploads) upload.abort();
    this.uploads.clear();
    this.current = undefined;
    this.onFailure();
  }

  private endUpload() {
    this.current?.end();
    this.current = undefined;
  }

  private enqueue(operation: () => Promise<unknown>) {
    const result = this.tail.then(() => {
      if (this.failure) throw this.failure;
      return operation();
    });
    // Model-start callbacks and streaming uploads run concurrently with inference.
    this.tail = result.catch((error: unknown) => {
      this.abort(
        error instanceof Error ? error : new Error("Agent transport failed"),
      );
    });
    return result;
  }
}
