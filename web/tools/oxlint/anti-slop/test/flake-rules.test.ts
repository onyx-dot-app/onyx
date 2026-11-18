import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";

const webDir = resolve(__dirname, "../../../..");

/** Lints one file with the test rules and returns `line rule` for each finding. */
function lint(filename: string, source: string): string[] {
  const cwd = mkdtempSync(join(tmpdir(), "onyx-oxlint-test-"));
  try {
    const rules = [
      "no-networkidle-in-tests",
      "no-real-time-wait-in-tests",
      "no-test-timeout-override",
      "require-test-skip-reason",
    ];
    const config = {
      jsPlugins: [
        {
          name: "anti-slop",
          specifier: join(webDir, "tools/oxlint/anti-slop/index.ts"),
        },
      ],
      rules: Object.fromEntries(
        rules.map((rule) => [`anti-slop/${rule}`, "error"])
      ),
    };
    writeFileSync(join(cwd, ".oxlintrc.json"), JSON.stringify(config));
    mkdirSync(join(cwd, dirname(filename)), { recursive: true });
    writeFileSync(join(cwd, filename), source);

    const result = spawnSync(
      join(webDir, "node_modules/.bin/oxlint"),
      ["--format", "json", filename],
      { cwd, encoding: "utf8" }
    );
    if (!result.stdout) throw result.error ?? new Error(result.stderr);
    const report: {
      diagnostics: { code: string; labels: { span: { line: number } }[] }[];
    } = JSON.parse(result.stdout);
    return report.diagnostics
      .filter(({ code }) => code.startsWith("anti-slop("))
      .map(
        ({ code, labels }) => `${labels[0]?.span.line} ${code.slice(10, -1)}`
      )
      .sort((a, b) => parseInt(a) - parseInt(b));
  } finally {
    rmSync(cwd, { recursive: true });
  }
}

test("flags Playwright waits, overrides and skips that hide a flake", () => {
  expect(
    lint(
      "tests/e2e/example.spec.ts",
      `import { test, expect } from "@playwright/test";
test.describe.configure({ retries: 2 });
test.describe.configure({ retries: 0, mode: "serial" });
test("case", { tag: "@x" }, async ({ page }) => {
  test.setTimeout(60000);
  test.skip(!process.env.CI, "");
  test.skip(!process.env.CI, "Needs the CI connector");
  await page.waitForTimeout(150);
  await page.waitForLoadState("networkidle");
  await page.goto("/", { waitUntil: "networkidle" });
  await page.goto("/", { "waitUntil": "networkidle" });
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(r)));
  await test.step("box", async () => {}, { box: true });
  await expect.poll(() => page.getByRole("row").count()).toBe(1);
});
test("details and a named body", { tag: "@x" }, body);
test.fixme("disabled without an issue", async () => {});
// Skip: Blocked by the upstream bug. https://github.com/example/repo/issues/123
test.fixme("disabled with an issue", async () => {});
`
    )
  ).toEqual([
    "2 no-test-timeout-override",
    "5 no-test-timeout-override",
    "6 require-test-skip-reason",
    "8 no-real-time-wait-in-tests",
    "9 no-networkidle-in-tests",
    "10 no-networkidle-in-tests",
    "11 no-networkidle-in-tests",
    "12 no-real-time-wait-in-tests",
    "17 require-test-skip-reason",
  ]);
});

test("flags Jest real-time waits, timeouts and skips", () => {
  expect(
    lint(
      "src/example.test.ts",
      `jest.retryTimes(2);
it("case", async () => {
  await new Promise((resolve) => setTimeout(resolve, 50));
  await jest.advanceTimersByTimeAsync(50);
}, 60000);
it.each([1])("case %s", () => {}, 60000);
xit("disabled", () => {});
it.skip.each([1])("disabled case %s", () => {});
beforeEach(() => {}, 60000);
`
    )
  ).toEqual([
    "1 no-test-timeout-override",
    "2 no-test-timeout-override",
    "3 no-real-time-wait-in-tests",
    "6 no-test-timeout-override",
    "7 require-test-skip-reason",
    "8 require-test-skip-reason",
    "9 no-test-timeout-override",
  ]);
});
