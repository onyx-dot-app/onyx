import { Page } from "@playwright/test";

const RUN_START_MS = Date.now();

/**
 * Captures a lightweight snapshot of the current page state to aid debugging of flaky flows.
 * Limits the amount of text collected so logs remain readable in CI.
 */
export async function logPageState(
  page: Page,
  context: string,
  logTag = "[e2e-page-debug]"
) {
  const sinceStartMs = Date.now() - RUN_START_MS;
  const snapshot: Record<string, unknown> = {
    context,
    timestamp: new Date().toISOString(),
    elapsedMs: sinceStartMs,
    elapsedSeconds: Number((sinceStartMs / 1000).toFixed(3)),
  };

  if (page.isClosed()) {
    snapshot.url = "<page-closed>";
    snapshot.title = "<unavailable>";
    snapshot.readyState = "<page-closed>";
    snapshot.bodySnippet = "<unavailable>";
    snapshot.visibleButtons = "<unavailable>";
    snapshot.visibleInputs = "<unavailable>";
    snapshot.note = "page was already closed before dump";
    console.log(`${logTag} ${JSON.stringify(snapshot)}`);
    return;
  }

  snapshot.url = page.url();

  try {
    snapshot.title = await page.title();
  } catch {
    snapshot.title = "<unavailable>";
  }

  try {
    snapshot.readyState = await page.evaluate(
      () => document.readyState ?? "<unknown>"
    );
  } catch {
    snapshot.readyState = "<unknown>";
  }

  try {
    const bodyText = await page.evaluate(() => document.body?.innerText ?? "");
    snapshot.bodySnippet = bodyText.trim().replace(/\s+/g, " ").slice(0, 500);
  } catch {
    snapshot.bodySnippet = "<unavailable>";
  }

  try {
    snapshot.visibleButtons = await page.evaluate(() =>
      Array.from(document.querySelectorAll("button"))
        .slice(0, 5)
        .map((btn) => ({
          text: btn.innerText,
          disabled: (btn as HTMLButtonElement).disabled,
          dataTestId: btn.getAttribute("data-testid"),
        }))
    );
  } catch {
    snapshot.visibleButtons = "<unavailable>";
  }

  try {
    snapshot.visibleInputs = await page.evaluate(() =>
      Array.from(
        document.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(
          "input, textarea"
        )
      )
        .slice(0, 5)
        .map((input) => ({
          name: input.name,
          type: input instanceof HTMLInputElement ? input.type : "textarea",
          value: input.value,
          dataTestId: input.getAttribute("data-testid"),
        }))
    );
  } catch {
    snapshot.visibleInputs = "<unavailable>";
  }

  console.log(`${logTag} ${JSON.stringify(snapshot)}`);
}
