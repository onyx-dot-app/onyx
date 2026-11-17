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
    if (status === "PENDING") await reports.expectPending();
    else await reports.expectFailure();
    await reports.reload();
    if (status === "PENDING") await reports.expectPending();
    else await reports.expectFailure();
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
  await reports.expectPending();
  showJob = false;
  await reports.expectCanGenerate();
});
