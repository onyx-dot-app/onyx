import { appendFileSync } from "node:fs";
import { relative } from "node:path";
import type { FullConfig, Reporter, Suite } from "@playwright/test/reporter";

export default class FlakyReporter implements Reporter {
  private suite?: Suite;

  onBegin(_config: FullConfig, suite: Suite): void {
    this.suite = suite;
  }

  onEnd(): void {
    const summary = process.env.GITHUB_STEP_SUMMARY;
    if (!summary || !this.suite) return;

    const flaky = this.suite
      .allTests()
      .filter((test) => test.outcome() === "flaky");
    const rows = flaky.map((test) => {
      const { file, line } = test.location;
      const location = relative(process.cwd(), file);
      const title = test.titlePath().filter(Boolean).join(" › ");
      return `${location}:${line} ${title}`.replace(/[\r\n]/g, " ");
    });

    appendFileSync(
      summary,
      `\n## Playwright tests that passed on retry (${rows.length})\n\n` +
        rows.map((row) => `    ${row}\n`).join("")
    );
  }
}
