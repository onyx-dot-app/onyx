import { execFile } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { promisify } from "node:util";

const webRoot = resolve(__dirname, "../../../..");
const run = promisify(execFile);
const effectDiagnostic = "anti-slop(no-unreasoned-state-sync)";

async function lint(source: string) {
  const directory = await mkdtemp(join(tmpdir(), "onyx-oxlint-"));
  const path = join(directory, "fixture.tsx");
  try {
    await writeFile(path, source);
    const { stdout } = await run(
      join(webRoot, "node_modules", ".bin", "oxlint"),
      ["--format", "json", path],
      { cwd: webRoot }
    ).catch((error: unknown) => {
      if (
        typeof error === "object" &&
        error !== null &&
        "code" in error &&
        error.code === 1 &&
        "stdout" in error &&
        typeof error.stdout === "string"
      ) {
        return { stdout: error.stdout };
      }
      throw error;
    });
    const result: unknown = JSON.parse(stdout);
    return result;
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

test("reports each effect call, including named aliases and member calls", async () => {
  const result = await lint(`
    import React, { useEffect, useLayoutEffect as useMeasure } from "react";
    import * as Hooks from "react";
    export function Panel() {
      useEffect(() => {}, []);
      useMeasure(() => {}, []);
      React.useLayoutEffect(() => {}, []);
      Hooks["useEffect"](() => {}, []);
      return null;
    }
  `);
  expect(result).toMatchObject({
    diagnostics: Array.from({ length: 4 }, () => ({
      code: effectDiagnostic,
      severity: "error",
    })),
  });
});

test("ignores comments, lookalike names, and references without a call", async () => {
  const result = await lint(`
    import { useEffect as useMeasure } from "react";
    // useEffect(() => {}, []);
    export const label = "useLayoutEffect(() => {}, [])";
    export const reference = useMeasure;
    export function otherCalls(useMeasure: () => void, matchCauseEffect: () => void) {
      useMeasure();
      matchCauseEffect();
    }
  `);
  expect(result).toMatchObject({ diagnostics: [] });
});

test.each([
  ["a reason", " -- focus the dialog when it opens", []],
  ["an empty reason", " --", ["anti-slop(require-suppression-reason)"]],
])("checks a suppression with %s", async (_name, reason, codes) => {
  const result = await lint(`
    import { useEffect } from "react";
    export function Panel() {
      // oxlint-disable-next-line anti-slop/no-unreasoned-state-sync${reason}
      useEffect(() => {}, []);
      return null;
    }
  `);
  expect(result).toMatchObject({
    diagnostics: codes.map((code) => ({ code, severity: "error" })),
  });
});
