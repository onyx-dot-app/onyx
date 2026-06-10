// Local dev watcher for @onyx-ai/shared. Rebuilds dist/ on edits so the web
// dev server (which consumes dist/, not src/) picks up changes on save.
//   - src/**         -> tsc --watch (incremental rebuild of JS + d.ts)
//   - tokens/**.json -> re-runs the Style Dictionary token build
//
// Run with `bun run dev`. Dev convenience only — never used by CI/build.
// Note: recursive fs.watch is supported on macOS/Windows; on Linux, re-run
// `bun run build:tokens` manually after editing tokens.

import { spawn } from "node:child_process";
import { watch } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const run = (script, extra = []) =>
  spawn("bun", ["run", script, ...extra], { cwd: root, stdio: "inherit" });

run("build:tokens"); // initial token build
run("build:ts", ["--", "--watch", "--preserveWatchOutput"]); // incremental TS watch

let timer;
watch(resolve(root, "tokens"), { recursive: true }, (_event, file) => {
  if (file && !file.endsWith(".json")) return;
  clearTimeout(timer);
  timer = setTimeout(() => run("build:tokens"), 150);
});

console.log(
  "[shared] watching src/ (tsc) + tokens/ (style-dictionary) — Ctrl-C to stop"
);
