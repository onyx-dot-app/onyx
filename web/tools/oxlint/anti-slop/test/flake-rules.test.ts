import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";

const webDir = resolve(__dirname, "../../../..");
const rules = [
  "no-frame-waits-in-tests",
  "no-networkidle-in-tests",
  "no-polling-loop-in-tests",
  "no-real-time-wait-in-tests",
  "no-test-timeout-override",
  "no-wall-clock-in-tests",
  "require-test-skip-reason",
  "require-suppression-reason",
];

function lint(
  filename: string,
  source: string,
  fixtures: Readonly<Record<string, string>> = {}
): string[] {
  const cwd = mkdtempSync(join(tmpdir(), "onyx-oxlint-test-"));
  try {
    const config = {
      jsPlugins: [
        {
          name: "anti-slop",
          specifier: join(webDir, "tools/oxlint/anti-slop/index.ts"),
        },
      ],
      overrides: [
        {
          files: ["tests/e2e/**", "**/*.test.ts", "**/*.test.tsx"],
          rules: Object.fromEntries(
            rules.map((rule) => [`anti-slop/${rule}`, "error"])
          ),
        },
      ],
    };
    writeFileSync(join(cwd, ".oxlintrc.json"), JSON.stringify(config));
    for (const [path, content] of Object.entries({
      ...fixtures,
      [filename]: source,
    })) {
      mkdirSync(join(cwd, dirname(path)), { recursive: true });
      writeFileSync(join(cwd, path), content);
    }

    const result = spawnSync(
      join(webDir, "node_modules/.bin/oxlint"),
      ["--format", "json", filename],
      { cwd, encoding: "utf8" }
    );
    if (result.error) throw result.error;
    if (!result.stdout) throw new Error(result.stderr);
    const report: { diagnostics: { code: string }[] } = JSON.parse(
      result.stdout
    );
    return report.diagnostics
      .map(({ code }) => code)
      .filter((code) => code.startsWith("anti-slop("))
      .sort();
  } finally {
    rmSync(cwd, { recursive: true });
  }
}

test("flags readiness races and hidden failures in Playwright", () => {
  const diagnostics = lint(
    "tests/e2e/example.spec.ts",
    `
      import { test as browserTest } from "@playwright/test";
      import { setTimeout as sleep } from "node:timers/promises";

      browserTest.describe.configure({ retries: 2 });
      browserTest("test", async ({ page }) => {
        browserTest.setTimeout(60000);
        browserTest.skip(process.env.CI, "");
        await page["waitForTimeout"](150);
        await page["waitForLoadState"]("networkidle");
        const options = { waitUntil: "networkidle" };
        await page.goto("/", options);
        while (!ready()) await sleep(10);
        await page.evaluate(() => new Promise(requestAnimationFrame));
        return Date["now"]();
      });
    `
  );
  expect(diagnostics).toEqual([
    "anti-slop(no-frame-waits-in-tests)",
    "anti-slop(no-networkidle-in-tests)",
    "anti-slop(no-networkidle-in-tests)",
    "anti-slop(no-polling-loop-in-tests)",
    "anti-slop(no-real-time-wait-in-tests)",
    "anti-slop(no-real-time-wait-in-tests)",
    "anti-slop(no-test-timeout-override)",
    "anti-slop(no-test-timeout-override)",
    "anti-slop(no-wall-clock-in-tests)",
    "anti-slop(require-test-skip-reason)",
  ]);
});

test("flags wall time after switching back from fake timers", () => {
  const diagnostics = lint(
    "src/example.test.ts",
    `
      import { jest as clock } from "@jest/globals";

      beforeEach(() => {
        clock.useFakeTimers().setSystemTime(new Date("2026-01-01"));
      });

      test("drives the fake clock", async () => {
        Date.now();
        const fired = new Promise((resolve) => setTimeout(resolve, 5));
        clock.advanceTimersByTime(5);
        await fired;
        clock.useRealTimers();
        new Date();
        await new Promise(setTimeout);
      }, 60000);

      xit("skipped", () => {});
    `
  );
  expect(diagnostics).toEqual([
    "anti-slop(no-real-time-wait-in-tests)",
    "anti-slop(no-test-timeout-override)",
    "anti-slop(no-wall-clock-in-tests)",
    "anti-slop(require-test-skip-reason)",
  ]);
});

test("flags per-case timeouts on array and tagged-table Jest tests", () => {
  expect(
    lint(
      "src/example.test.ts",
      `
        it.each([1])("has a timeout", () => {}, 60000);
        it.each\`value
          \${1}
        \`("has a timeout", () => {}, 60000);
        it.each([1])("uses the project timeout", () => {});
      `
    )
  ).toEqual([
    "anti-slop(no-test-timeout-override)",
    "anti-slop(no-test-timeout-override)",
  ]);
});

test("allows observable waits, bounded microtask flushes, and tracked skips", () => {
  expect(
    lint(
      "tests/e2e/example.spec.ts",
      `
        import { test, expect } from "@playwright/test";

        test("needs a connector", async ({ page }) => {
          test.skip(!process.env.ENABLE_CONNECTOR, "Connector is optional");
          await expect.poll(() => page.getByRole("row").count()).toBe(1);
          for (let index = 0; index < 3; index++) await Promise.resolve();
          new Date("2026-01-01");
        });

        // Skip: Enable after the upstream fix. https://github.com/example/repo/issues/123
        test.fixme("blocked by upstream", () => {});
      `
    )
  ).toEqual([]);
});

test("uses the existing reason check for lint suppressions", () => {
  expect(
    lint(
      "src/example.test.ts",
      `
        // oxlint-disable-next-line anti-slop/no-wall-clock-in-tests
        Date.now();
      `
    )
  ).toEqual(["anti-slop(require-suppression-reason)"]);
});

test("leaves production code outside the test overrides", () => {
  expect(lint("src/example.ts", "export const now = Date.now();")).toEqual([]);
});

test("follows aliased Playwright fixtures through local exports", () => {
  expect(
    lint(
      "tests/e2e/example.spec.ts",
      `
        import { runner as world, unrelated } from "./support";
        world.skip("needs a reason", () => {});
        world.setTimeout(60000);
        unrelated.skip();
      `,
      {
        "tests/e2e/support.ts": `export { scenario as runner, unrelated } from "./case";`,
        "tests/e2e/case.ts": `
          import { test as base } from "@playwright/test";
          export const scenario = base.extend({}).extend({});
          export const unrelated = { skip() {} };
        `,
      }
    )
  ).toEqual([
    "anti-slop(no-test-timeout-override)",
    "anti-slop(require-test-skip-reason)",
  ]);
});

test("recognizes concise timer setup callbacks", () => {
  expect(
    lint(
      "src/example.test.ts",
      `
        describe("each", () => {
          beforeEach(() => jest.useFakeTimers());
          it("uses a fake clock", () => { Date.now(); });
        });
        describe("all", () => {
          beforeAll(() => jest.useFakeTimers());
          it("uses a fake clock", () => { Date.now(); });
        });
      `
    )
  ).toEqual([]);
});

test("applies per-test timer setup after one-time hooks in enclosing suites", () => {
  expect(
    lint(
      "src/example.test.ts",
      `
        describe("real timers", () => {
          beforeEach(() => { jest.useFakeTimers(); });
          beforeEach(() => { jest.useRealTimers(); });
          beforeAll(() => { jest.useFakeTimers(); });
          describe("nested", () => {
            beforeAll(() => { jest.useFakeTimers(); });
            test("uses real timers", () => { Date.now(); });
          });
        });
      `
    )
  ).toEqual(["anti-slop(no-wall-clock-in-tests)"]);

  expect(
    lint(
      "src/example.test.ts",
      `
        describe("fake timers", () => {
          beforeEach(() => { jest.useFakeTimers(); });
          beforeAll(() => { jest.useRealTimers(); });
          test("uses fake timers", () => { Date.now(); });
        });
      `
    )
  ).toEqual([]);
});
