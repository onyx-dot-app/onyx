import { execFile } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { promisify } from "node:util";

const webRoot = resolve(__dirname, "../../../..");
const run = promisify(execFile);

async function diagnosticCodes(source: string): Promise<string[]> {
  const directory = await mkdtemp(join(tmpdir(), "onyx-oxlint-"));
  const path = join(directory, "fixture.tsx");
  try {
    await writeFile(path, source);
    const { stdout } = await run(
      join(webRoot, "node_modules", ".bin", "oxlint"),
      ["--format", "json", path],
      { cwd: webRoot }
    ).catch((error: { code?: number; stdout?: string }) => {
      if (error.code === 1 && error.stdout) return { stdout: error.stdout };
      throw error;
    });
    const result: { diagnostics: { code: string }[] } = JSON.parse(stdout);
    return result.diagnostics.map((diagnostic) => diagnostic.code);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

test("reports direct and member effect calls, not lookalikes", async () => {
  const codes = await diagnosticCodes(`
    import React, { useEffect } from "react";
    // useEffect(() => {}, []);
    export const label = "useLayoutEffect(() => {}, [])";
    export const reference = useEffect;
    export function Panel(matchCauseEffect: () => void) {
      useEffect(() => {}, []);
      React.useLayoutEffect(() => {}, []);
      matchCauseEffect();
      return null;
    }
  `);
  expect(codes).toEqual([
    "anti-slop(no-unreasoned-state-sync)",
    "anti-slop(no-unreasoned-state-sync)",
  ]);
});

test.each([
  ["a reason", " -- focus the dialog when it opens", []],
  ["an empty reason", " --", ["anti-slop(require-suppression-reason)"]],
])("checks a suppression with %s", async (_name, reason, expected) => {
  const codes = await diagnosticCodes(`
    import { useEffect } from "react";
    export function Panel() {
      // oxlint-disable-next-line anti-slop/no-unreasoned-state-sync${reason}
      useEffect(() => {}, []);
      return null;
    }
  `);
  expect(codes).toEqual(expected);
});
