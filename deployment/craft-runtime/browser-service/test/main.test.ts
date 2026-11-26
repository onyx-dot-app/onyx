import * as assert from "node:assert/strict";
import * as NodeChild from "node:child_process";
import * as NodeCrypto from "node:crypto";
import * as NodeFSP from "node:fs/promises";
import * as NodeOS from "node:os";
import * as NodePath from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { launchChrome, ok, startSite } from "./helpers.ts";

const MAIN = fileURLToPath(new URL("../main.ts", import.meta.url));

test("main.ts --check exits cleanly", () => {
  const output = NodeChild.execFileSync(process.execPath, [MAIN, "--check"], { encoding: "utf8" });
  assert.equal(output.trim(), "browser-service ok");
});

test("main.ts serves agent calls and enforces the tab limit", async () => {
  const cleanups: Array<() => Promise<unknown>> = [];
  try {
    const chrome = await launchChrome();
    cleanups.unshift(() => chrome.stop());
    const site = await startSite();
    cleanups.unshift(() => site.stop());
    const dir = await NodeFSP.mkdtemp(NodePath.join(NodeOS.tmpdir(), "onyx-browser-main-"));
    cleanups.unshift(() => NodeFSP.rm(dir, { recursive: true, force: true }));
    const socketPath = NodePath.join(dir, "service.sock");
    const child = NodeChild.spawn(process.execPath, [MAIN], {
      env: {
        ...process.env,
        ONYX_BROWSER_CDP_URL: chrome.cdpUrl,
        ONYX_BROWSER_SOCKET: socketPath,
        ONYX_SESSIONS_ROOT: dir,
        TMPDIR: dir,
      },
      stdio: ["ignore", "ignore", "pipe"],
    });
    let ended: string | null = null;
    const exited = new Promise<void>((resolve) => {
      child.once("error", (error) => {
        ended = String(error);
        resolve();
      });
      child.once("exit", (code, signal) => {
        ended = `exit ${code ?? signal}`;
        resolve();
      });
    });
    cleanups.unshift(async () => {
      child.kill("SIGTERM");
      await exited;
    });
    let stderr = "";
    child.stderr.on("data", (chunk: Buffer) => (stderr += chunk.toString()));
    const deadline = Date.now() + 15_000;
    while (!stderr.includes('"event":"listening"')) {
      assert.equal(ended, null, `service stopped before it listened: ${stderr}`);
      assert.ok(Date.now() < deadline, `service did not start: ${stderr}`);
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    const chat = NodeCrypto.randomUUID();
    const opened = await ok(socketPath, chat, "open", { url: `${site.url}/form` });
    assert.equal((opened.tab as { title: string }).title, "Form page");
    const snap = await ok(socketPath, chat, "snapshot");
    assert.match(snap.text as string, /button "Press me"/);
    const opens = await Promise.allSettled(
      Array.from({ length: 9 }, () => ok(socketPath, chat, "open", { newTab: true })),
    );
    const failures = opens.filter((each) => each.status === "rejected");
    assert.equal(failures.length, 2);
    for (const failure of failures) assert.match(String(failure.reason), /tab_limit/);
    // Every event is one JSON line.
    for (const line of stderr.trim().split("\n")) JSON.parse(line);
  } finally {
    for (const cleanup of cleanups) await cleanup().catch(() => {});
  }
});
