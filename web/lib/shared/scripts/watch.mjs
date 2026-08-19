// Local dev watcher for @onyx-ai/shared. Rebuilds dist/ on edits:
//   - src/**         -> tsc --watch (incremental rebuild of JS + d.ts)
//   - tokens/**.json -> Style Dictionary token build, THEN re-inlines the result
//                       into Opal's dist (bundle-css) so the web dev server — which
//                       consumes opal/dist/root.css, not shared/dist — hot-reloads.
//
// Run with `bun run dev` (pair it with web's `bun run dev`). Dev convenience only,
// never used by CI/build. Note: recursive fs.watch works on macOS/Windows; on Linux,
// re-run `bun run build:tokens` (then opal's `bun run build`) after editing tokens.

import { spawn } from "node:child_process";
import { watch } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const opalRoot = resolve(root, "..", "opal");
const run = (script, extra = []) =>
  spawn("bun", ["run", script, ...extra], { cwd: root, stdio: "inherit" });

// Rebuild tokens, then re-inline them into Opal's dist/root.css. Opal bakes shared's
// CSS in at build time, so the web dev server only sees a token change once Opal is
// re-bundled. bundle-css.mjs is pure Node and fast, so chaining it here is cheap.
function rebuildTokens() {
  spawn("bun", ["run", "build:tokens"], { cwd: root, stdio: "inherit" }).on(
    "exit",
    (code) => {
      if (code === 0) {
        spawn("node", ["scripts/bundle-css.mjs"], {
          cwd: opalRoot,
          stdio: "inherit",
        });
      }
    }
  );
}

rebuildTokens(); // initial token build (+ Opal re-inline)
run("build:ts", ["--", "--watch", "--preserveWatchOutput"]); // incremental TS watch

let timer;
watch(resolve(root, "tokens"), { recursive: true }, (_event, file) => {
  if (file && !file.endsWith(".json")) return;
  clearTimeout(timer);
  timer = setTimeout(rebuildTokens, 150);
});

console.log(
  "[shared] watching src/ (tsc) + tokens/ (style-dictionary) — Ctrl-C to stop"
);
