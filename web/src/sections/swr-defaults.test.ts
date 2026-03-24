/**
 * Static analysis tests for SWR usage in always-mounted components.
 *
 * These tests read the source files of components that are mounted in
 * the root layout (sidebar, health banner, etc.) and verify that any
 * useSWR call either:
 *   (a) has an explicit config object, OR
 *   (b) relies on the global SWRConfig (which disables aggressive defaults)
 *
 * This prevents regressions where a new unguarded useSWR call in a
 * layout-level component causes unbounded request growth in cloud
 * multi-tenant deployments.
 */

import * as fs from "fs";
import * as path from "path";

const SRC_ROOT = path.resolve(__dirname, "..");

/**
 * Components that are always mounted (in root layout, sidebar, or
 * top-level providers). Any useSWR call in these files MUST have an
 * explicit config object — even if it's just `{}` — to signal that
 * the developer considered the revalidation behavior.
 */
const ALWAYS_MOUNTED_FILES = [
  "sections/AppHealthBanner.tsx",
  "sections/sidebar/UserAvatarPopover.tsx",
  "sections/sidebar/NotificationsPopover.tsx",
  "sections/sidebar/AppSidebar.tsx",
  "components/chat/ProviderContext.tsx",
  "hooks/useCurrentUser.ts",
];

/**
 * Matches useSWR calls that have NO config object (only key + fetcher).
 *
 * Pattern: useSWR<...>(key, fetcher) with NO third argument.
 * We look for `useSWR` followed by a closing paren after exactly two args
 * (the key and fetcher) with no trailing config object.
 *
 * This is a heuristic — it catches the most common pattern:
 *   useSWR("/api/foo", errorHandlingFetcher)
 *   useSWR<Type>("/api/foo", errorHandlingFetcher)
 *
 * but intentionally does NOT flag:
 *   useSWR("/api/foo", errorHandlingFetcher, { ... })
 *   useSWR("/api/foo", errorHandlingFetcher, config)
 */
function findUnconfiguredSWRCalls(
  source: string
): { line: number; text: string }[] {
  const lines = source.split("\n");
  const results: { line: number; text: string }[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!.trim();

    // Skip comments
    if (line.startsWith("//") || line.startsWith("*")) continue;

    // Match: useSWR(... or useSWR<...>(... that only has two arguments
    if (/useSWR[^(]*\(/.test(line)) {
      // Collect the full call (might span multiple lines)
      let fullCall = "";
      let parenDepth = 0;
      let started = false;

      for (let j = i; j < Math.min(i + 10, lines.length); j++) {
        fullCall += lines[j]! + "\n";
        for (const ch of lines[j]!) {
          if (ch === "(") {
            parenDepth++;
            started = true;
          }
          if (ch === ")") parenDepth--;
        }
        if (started && parenDepth === 0) break;
      }

      // Count top-level commas (arguments) in the useSWR call
      // If there are only 2 args (key, fetcher), it's unconfigured
      let depth = 0;
      let commaCount = 0;
      let inCall = false;

      for (const ch of fullCall) {
        if (ch === "(") {
          depth++;
          if (depth === 1) inCall = true;
        }
        if (ch === ")") depth--;
        if (inCall && depth === 1 && ch === ",") commaCount++;
        if (inCall && depth === 0) break;
      }

      // 1 comma = 2 args (key, fetcher) — no config
      if (commaCount === 1) {
        results.push({ line: i + 1, text: line });
      }
    }
  }

  return results;
}

describe("SWR usage in always-mounted components", () => {
  for (const relPath of ALWAYS_MOUNTED_FILES) {
    const filePath = path.join(SRC_ROOT, relPath);

    it(`${relPath} — all useSWR calls must have a config object`, () => {
      if (!fs.existsSync(filePath)) {
        // File was removed/moved — not a failure
        return;
      }

      const source = fs.readFileSync(filePath, "utf-8");
      const unconfigured = findUnconfiguredSWRCalls(source);

      if (unconfigured.length > 0) {
        const details = unconfigured
          .map((c) => `  line ${c.line}: ${c.text}`)
          .join("\n");

        throw new Error(
          `Found useSWR call(s) without explicit config in always-mounted ` +
            `component ${relPath}. In cloud deployments, unguarded SWR calls ` +
            `inherit default revalidation behavior that can cause unbounded ` +
            `request growth. Add a config object (even if empty) to signal ` +
            `that revalidation behavior was considered:\n${details}`
        );
      }
    });
  }
});

describe("Global SWRConfig exists in AppProvider", () => {
  it("AppProvider wraps children in SWRConfig", () => {
    const appProviderPath = path.join(SRC_ROOT, "providers/AppProvider.tsx");
    const source = fs.readFileSync(appProviderPath, "utf-8");

    expect(source).toContain("SWRConfig");
    expect(source).toContain("revalidateOnFocus: false");
    expect(source).toContain("revalidateOnReconnect: false");
  });
});
