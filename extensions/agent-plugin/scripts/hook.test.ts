// Runs hook.ts as Claude Code and Codex do: one process per event, JSON on stdin.
import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const HOOK = join(import.meta.dir, "hook.ts");
const PROMPT = "What is our refund policy for enterprise customers?";
const NUDGE =
  "This turn answered after Onyx raw retrieval only. If the answer relies on " +
  "company knowledge beyond what the prefetch returned, call search_indexed_documents on the Onyx MCP server now and revise. " +
  "Otherwise finish.";

type Host = "claude" | "codex";

let server: ReturnType<typeof Bun.serve>;
let prefetchEnv: Record<string, string>;
const dataDirs: string[] = [];

// The developer's own plugin settings must not leak into the hook under test.
const baseEnv = Object.fromEntries(
  Object.entries(process.env).filter(
    ([name]) => !name.startsWith("ONYX_") && !name.startsWith("CLAUDE_PLUGIN_"),
  ),
);

beforeAll(() => {
  server = Bun.serve({
    port: 0,
    fetch: (req) =>
      new URL(req.url).pathname === "/api/search/raw" && req.method === "POST"
        ? Response.json({
            results: [
              {
                title: "Refund policy",
                content: "Enterprise refunds need finance approval.",
                link: "https://kb/refunds",
                source_type: "confluence",
                updated_at: "2026-01-01",
              },
            ],
          })
        : new Response("not found", { status: 404 }),
  });
  prefetchEnv = {
    ONYX_PREFETCH: "true",
    ONYX_STRICT_RETRIEVAL: "true",
    ONYX_URL: `http://127.0.0.1:${server.port}`,
    ONYX_API_TOKEN: "test-token",
  };
});

afterAll(() => {
  server.stop(true);
  for (const dir of dataDirs) {
    rmSync(dir, { recursive: true, force: true });
  }
});

function session(env: Record<string, string>) {
  const dataDir = mkdtempSync(join(tmpdir(), "onyx-hook-test-"));
  dataDirs.push(dataDir);
  const id = "session-1";
  // Async so the test's own server can answer the hook's prefetch.
  const run = async (host: Host, input: Record<string, unknown>) => {
    const proc = Bun.spawn({
      // No .env from the working directory either.
      cmd: ["bun", "--no-env-file", HOOK, ...(host === "codex" ? ["codex"] : [])],
      stdin: Buffer.from(JSON.stringify({ session_id: id, ...input })),
      env: { ...baseEnv, ...env, CLAUDE_PLUGIN_DATA: dataDir },
      stdout: "pipe",
      stderr: "pipe",
    });
    const [stdout, stderr] = await Promise.all([
      new Response(proc.stdout).text(),
      new Response(proc.stderr).text(),
    ]);
    // The hook logs failures and exits 0, so silence is the only proof of success.
    expect(stderr).toBe("");
    expect(await proc.exited).toBe(0);
    return stdout ? (JSON.parse(stdout) as Record<string, unknown>) : null;
  };
  const state = () =>
    JSON.parse(readFileSync(join(dataDir, "sessions", `${id}.json`), "utf8"));
  return { run, state };
}

async function prefetchThenStop(host: Host) {
  const s = session(prefetchEnv);
  const prompt = await s.run(host, { hook_event_name: "UserPromptSubmit", prompt: PROMPT });
  expect(JSON.stringify(prompt)).toContain("https://kb/refunds");
  expect(s.state()).toEqual({ consulted: true, awaitingFullSearch: true });
  return s;
}

describe("Codex continuation", () => {
  test("prefetch, Stop block, replayed nudge, silent second Stop", async () => {
    const s = await prefetchThenStop("codex");
    expect(await s.run("codex", { hook_event_name: "Stop", stop_hook_active: false })).toEqual({
      decision: "block",
      reason: NUDGE,
    });
    // Codex sends the reason back as a user prompt: no context, state untouched.
    expect(await s.run("codex", { hook_event_name: "UserPromptSubmit", prompt: NUDGE })).toBeNull();
    expect(s.state()).toEqual({ consulted: true, awaitingFullSearch: true });
    expect(await s.run("codex", { hook_event_name: "Stop", stop_hook_active: true })).toBeNull();
  });

  test("a full search clears the pending nudge", async () => {
    const s = await prefetchThenStop("codex");
    await s.run("codex", {
      hook_event_name: "PostToolUse",
      tool_name: "mcp__onyx__search_indexed_documents",
    });
    expect(s.state()).toEqual({ consulted: true, awaitingFullSearch: false });
    expect(await s.run("codex", { hook_event_name: "Stop", stop_hook_active: false })).toBeNull();
  });
});

describe("Claude Code continuation", () => {
  test("Stop continues the turn through additionalContext", async () => {
    const s = await prefetchThenStop("claude");
    expect(await s.run("claude", { hook_event_name: "Stop", stop_hook_active: false })).toEqual({
      hookSpecificOutput: { hookEventName: "Stop", additionalContext: NUDGE },
    });
    expect(await s.run("claude", { hook_event_name: "Stop", stop_hook_active: true })).toBeNull();
  });
});

describe("steering and the strict gate", () => {
  test("the directive needs no credentials", async () => {
    const s = session({});
    const out = await s.run("codex", { hook_event_name: "UserPromptSubmit", prompt: PROMPT });
    expect(JSON.stringify(out)).toContain("search_indexed_documents on the Onyx MCP server");
    expect(s.state()).toEqual({ consulted: false, awaitingFullSearch: false });
  });

  test("other retrieval tools wait for the Onyx tool under either server name", async () => {
    const s = session({ ONYX_STRICT_RETRIEVAL: "true" });
    await s.run("claude", { hook_event_name: "UserPromptSubmit", prompt: PROMPT });
    const pre = (tool: string) =>
      s.run("claude", { hook_event_name: "PreToolUse", tool_name: tool });
    const denied = { hookSpecificOutput: { permissionDecision: "deny" } };
    expect(await pre("mcp__other__search_docs")).toMatchObject(denied);
    expect(await pre("WebSearch")).toMatchObject(denied);
    expect(await pre("mcp__onyx__external__search")).toMatchObject(denied);
    expect(await pre("mcp__other__create_issue")).toBeNull();
    expect(await pre("mcp__onyx__search_indexed_documents")).toBeNull();
    expect(await pre("mcp__plugin_onyx_onyx__search_indexed_documents")).toBeNull();
    await s.run("claude", {
      hook_event_name: "PostToolUseFailure",
      tool_name: "mcp__plugin_onyx_onyx__search_indexed_documents",
    });
    expect(await pre("mcp__other__search_docs")).toBeNull();
  });
});
