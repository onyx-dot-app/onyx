import { test } from "@playwright/test";
import { UsageReportsPage } from "@tests/e2e/pages/UsageReportsPage";

for (const status of ["PENDING", "FAILURE"] as const) {
  test(`usage report ${status} state survives reload`, async ({ page }) => {
    await page.route("**/api/admin/usage-report-jobs", (route) =>
      route.fulfill({
        json: [
          {
            report_id: crypto.randomUUID(),
            status,
            time_created: new Date().toISOString(),
          },
        ],
      })
    );
    const reports = new UsageReportsPage(page);
    await reports.goto();
    if (status === "PENDING") await reports.expectPendingRow();
    else await reports.expectFailure();
    await reports.reload();
    if (status === "PENDING") await reports.expectPendingRow();
    else await reports.expectFailure();
    // A job this page did not request, such as another admin's, does not
    // block a new request.
    await reports.expectCanGenerate();
  });
}

test("a report removed after retention does not block new requests", async ({
  page,
}) => {
  let showJob = false;
  let reportId = crypto.randomUUID();
  await page.route("**/api/admin/usage-report-jobs", (route) =>
    route.fulfill({
      json: showJob
        ? [
            {
              report_id: reportId,
              status: "PENDING",
              time_created: new Date().toISOString(),
            },
          ]
        : [],
    })
  );
  await page.route("**/api/admin/usage-report", async (route) => {
    if (route.request().method() === "POST") {
      const body: { report_id: string } = route.request().postDataJSON();
      reportId = body.report_id;
      showJob = true;
      await route.fulfill({ status: 204 });
    } else await route.fulfill({ json: [] });
  });
  const reports = new UsageReportsPage(page);
  await reports.goto();
  await reports.generateReport();
  await reports.expectGenerating();
  showJob = false;
  await reports.expectCanGenerate();
});

test("a report that finishes during page load appears", async ({ page }) => {
  const reportId = crypto.randomUUID();
  let committed = false;
  // The jobs read lands just after the worker commits the report and deletes
  // its job. A reports read sent at the same time as the jobs read is stale.
  await page.route("**/api/admin/usage-report-jobs", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 500));
    committed = true;
    await route.fulfill({ json: [] });
  });
  await page.route("**/api/admin/usage-report", (route) =>
    route.fulfill({
      json: committed
        ? [
            {
              report_name: `2026-01-01_${reportId}_usage_report.zip`,
              requestor: "admin_user@example.com",
              time_created: new Date().toISOString(),
              period_from: null,
              period_to: null,
            },
          ]
        : [],
    })
  );
  const reports = new UsageReportsPage(page);
  await reports.goto();
  await reports.expectReport("All time");
});
