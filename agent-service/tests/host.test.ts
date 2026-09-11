import { expect, test } from "bun:test";
import { HttpHost, RunApi } from "../src/host";

test("HTTP host orders model_start, buffered deltas, model_end and tool callback", async () => {
  const received: unknown[] = [];
  const server = Bun.serve({
    port: 0,
    async fetch(request) {
      expect(request.headers.get("authorization")).toBe("Bearer secret");
      expect(request.headers.get("x-onyx-tenant-id")).toBe("tenant");
      if (new URL(request.url).pathname.endsWith("events-stream")) {
        const lines = (await request.text()).trim().split("\n");
        received.push({
          attemptId: request.headers.get("x-onyx-attempt-id"),
          sequence: Number(request.headers.get("x-onyx-sequence")),
          events: lines.flatMap((line) => JSON.parse(line).events),
        });
      } else received.push(await request.json());
      return Response.json({ value: "ok" });
    },
  });
  const host = new HttpHost(
    new RunApi(
      server.url.toString().slice(0, -1),
      "secret",
      "run",
      "tenant",
      "attempt",
    ),
    () => {},
  );
  try {
    const started = host.request("model_start");
    host.send({ type: "chunk", delta: "a" });
    host.send({ type: "chunk", delta: "b" });
    host.send({ type: "model_end" });
    expect(await host.request("tools", { calls: [] })).toBe("ok");
    await started;
    await host.flush();
    expect(received).toEqual([
      { attemptId: "attempt", type: "model_start", payload: {}, sequence: 1 },
      {
        attemptId: "attempt",
        sequence: 2,
        events: [
          { type: "chunk", delta: "a" },
          { type: "chunk", delta: "b" },
          { type: "model_end" },
        ],
      },
      {
        attemptId: "attempt",
        type: "tools",
        payload: { calls: [] },
        sequence: 3,
      },
    ]);
  } finally {
    host.abort();
    await server.stop(true);
  }
});

test("HTTP host failure aborts the model without replaying events or callbacks", async () => {
  let count = 0;
  let aborted = false;
  const server = Bun.serve({
    port: 0,
    fetch() {
      count++;
      return new Response("failed", { status: 503 });
    },
  });
  const host = new HttpHost(
    new RunApi(
      server.url.toString().slice(0, -1),
      "secret",
      "run",
      "tenant",
      "attempt",
    ),
    () => {
      aborted = true;
    },
  );
  try {
    host.send({ type: "model_end" });
    await expect(host.request("tools")).rejects.toThrow(
      "events-stream failed (503)",
    );
    await expect(host.flush()).rejects.toThrow("events-stream failed (503)");
    expect({ count, aborted }).toEqual({ count: 1, aborted: true });
  } finally {
    host.abort();
    await server.stop(true);
  }
});

test("HTTP host caps pending delivery bytes while callbacks are blocked", async () => {
  const server = Bun.serve({
    port: 0,
    async fetch() {
      await Bun.sleep(100);
      return Response.json({ value: null });
    },
  });
  let aborted = false;
  const host = new HttpHost(
    new RunApi(
      server.url.toString().slice(0, -1),
      "secret",
      "run",
      "tenant",
      "attempt",
    ),
    () => {
      aborted = true;
    },
  );
  try {
    host.send({ type: "chunk", content: "x".repeat(600_000) });
    expect(() =>
      host.send({ type: "chunk", content: "x".repeat(600_000) }),
    ).toThrow("capacity exceeded");
    await expect(host.flush()).rejects.toThrow("capacity exceeded");
    expect(aborted).toBe(true);
  } finally {
    host.abort();
    await server.stop(true);
  }
});

test("model deltas reach the API before model_end and tools wait for the stream checkpoint", async () => {
  const received: string[] = [];
  let release!: () => void;
  const checkpoint = new Promise<void>((resolve) => {
    release = resolve;
  });
  const server = Bun.serve({
    port: 0,
    async fetch(request) {
      if (new URL(request.url).pathname.endsWith("events-stream")) {
        let pending = "";
        for await (const chunk of request.body!) {
          pending += new TextDecoder().decode(chunk);
          let newline: number;
          while ((newline = pending.indexOf("\n")) >= 0) {
            const frame = JSON.parse(pending.slice(0, newline));
            received.push(
              ...frame.events.map((event: { type: string }) => event.type),
            );
            pending = pending.slice(newline + 1);
          }
        }
        await checkpoint;
        return Response.json({ ok: true });
      }
      received.push(((await request.json()) as { type: string }).type);
      return Response.json({ value: null });
    },
  });
  const host = new HttpHost(
    new RunApi(
      server.url.toString().slice(0, -1),
      "secret",
      "run",
      "tenant",
      "attempt",
    ),
    () => {},
    10,
  );
  try {
    await host.request("model_start");
    host.send({ type: "chunk", content: "visible while generation is active" });
    for (let i = 0; i < 100 && !received.includes("chunk"); i++)
      await Bun.sleep(10);
    expect(received).toEqual(["model_start", "chunk"]);
    host.send({ type: "model_end" });
    const tool = host.request("tools", { calls: [] });
    await Bun.sleep(30);
    expect(received).toEqual(["model_start", "chunk", "model_end"]);
    release();
    await tool;
    expect(received).toEqual(["model_start", "chunk", "model_end", "tools"]);
  } finally {
    release();
    host.abort();
    await server.stop(true);
  }
});
