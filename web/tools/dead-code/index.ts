import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

import { findDeadCss } from "./css.ts";

/**
 * The frontend dead code gate.
 *
 * Two engines, one report, one exit code:
 *   - knip covers unused files, exports, types and dependencies. Its config is
 *     web/knip.config.ts.
 *   - tools/dead-code/css.ts covers CSS classes, custom properties and design
 *     tokens, which knip does not model.
 *
 * There is no baseline. Any finding fails the command.
 */

const WEB_ROOT = resolve(import.meta.dirname, "../..");
const REPO_ROOT = resolve(WEB_ROOT, "..");

/**
 * Names the CSS checker must never report. Each one needs a reason: an entry
 * here is a permanent exemption, not a baseline.
 */
const CSS_IGNORE: readonly string[] = [
  // Toggled from outside the design system: next-themes writes `.dark` on
  // <html>, and Tailwind's own `dark` variant keys off it.
  "dark",
];

function runKnip(): boolean {
  const result = spawnSync(
    "bunx",
    ["knip", "--no-progress", "--no-config-hints"],
    { cwd: WEB_ROOT, stdio: "inherit" }
  );
  if (result.error !== undefined) {
    console.error(`Could not run knip: ${result.error.message}`);
    return false;
  }
  return result.status === 0;
}

async function runCssCheck(): Promise<boolean> {
  const findings = await findDeadCss({
    webRoot: WEB_ROOT,
    // mobile/ reads the shared design tokens through NativeWind. Without it in
    // the corpus, every mobile-only token looks dead.
    extraCorpusRoots: [resolve(REPO_ROOT, "mobile")],
    ignore: CSS_IGNORE,
  });

  if (findings.length === 0) {
    console.log("No unused CSS classes, custom properties or design tokens.");
    return true;
  }

  console.log(`\nUnused CSS and design tokens (${findings.length})`);
  const width = Math.max(...findings.map((finding) => finding.name.length));
  for (const finding of findings) {
    const name = finding.name.padEnd(width);
    const kind = finding.kind.padEnd(8);
    console.log(`${name}  ${kind}  ${finding.file}:${finding.line}`);
  }
  return false;
}

const knipClean = runKnip();
const cssClean = await runCssCheck();

if (!knipClean || !cssClean) {
  console.error(
    "\nDead code found. Delete it, or add a commented exemption if the tool is wrong."
  );
  process.exitCode = 1;
}
