import { expect, test } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { AdminIntegrationsPage } from "@tests/e2e/pages/AdminIntegrationsPage";
import { AdminIntegrationDetailPage } from "@tests/e2e/pages/AdminIntegrationDetailPage";
import {
  ApiAppUpstream,
  TICKET_ACTIONS,
  ticketsOpenApiYaml,
} from "@tests/e2e/utils/apiAppUpstream";

test.describe("Custom REST app", () => {
  let createdId: number | null = null;
  let upstream: ApiAppUpstream;

  test.beforeAll(async () => {
    upstream = await ApiAppUpstream.start();
  });

  test.afterAll(async () => {
    await upstream.stop();
  });

  test.afterEach(async ({ browser }) => {
    if (createdId === null) return;
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    try {
      await new OnyxApiClient(context.request).deleteIntegration(createdId);
    } finally {
      await context.close();
      createdId = null;
    }
  });

  test("adds an app from typed endpoint lines and edits one line", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const name = `PW Tickets ${Date.now()}`;
    const integrations = new AdminIntegrationsPage(page);
    const detail = new AdminIntegrationDetailPage(page);

    await integrations.goto();
    await integrations.openAdd("Custom API");
    await integrations.fillCustomApi({
      name,
      baseUrl: "https://tickets.example.com/api",
      endpoints: [
        "GET /tickets/{id} Read a ticket",
        "GET /tickets?status&limit List tickets",
        "POST /tickets Create a ticket",
      ],
    });
    createdId = await integrations.submit();
    await detail.expectLoaded(name);

    await detail.openTab("Actions");
    await expect(detail.policyButton("Read a ticket", "Allow")).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    await expect(detail.policyButton("List tickets", "Allow")).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    await expect(detail.policyButton("Create a ticket", "Ask")).toHaveAttribute(
      "aria-pressed",
      "true"
    );

    await detail.replaceEndpoints([
      "GET /tickets/{id} Show one ticket",
      "GET /tickets?status&limit List tickets",
      "POST /tickets Create a ticket",
    ]);
    await detail.expectEndpoints([
      "GET /tickets/{id} Show one ticket",
      "GET /tickets?status&limit List tickets",
      "POST /tickets Create a ticket",
    ]);
    await detail.openTab("Actions");
    await expect(
      detail.policyButton("Show one ticket", "Allow")
    ).toHaveAttribute("aria-pressed", "true");
    await detail.expectActionAbsent("Read a ticket");
  });

  test("adds an app from a spec URL and edits its base URL", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const name = `PW Spec URL ${Date.now()}`;
    const integrations = new AdminIntegrationsPage(page);
    const detail = new AdminIntegrationDetailPage(page);

    await integrations.goto();
    await integrations.openAdd("Custom API");
    await integrations.fillDetectedApi({
      name,
      url: upstream.specUrl(name),
      detected: "REST API, 2 endpoints",
    });
    createdId = await integrations.submit();
    await detail.expectLoaded(name);
    await detail.openTab("Actions");
    await expect(
      detail.policyButton(TICKET_ACTIONS.read.summary, "Allow")
    ).toHaveAttribute("aria-pressed", "true");
    await expect(
      detail.policyButton(TICKET_ACTIONS.create.summary, "Ask")
    ).toHaveAttribute("aria-pressed", "true");

    await detail.openTab("Configuration");
    await detail.expectBaseUrl(upstream.apiBaseUrl);
    const movedBaseUrl = `${upstream.apiBaseUrl}/v2`;
    await detail.replaceBaseUrl(movedBaseUrl);
    await detail.reload();
    await detail.openTab("Configuration");
    await detail.expectBaseUrl(movedBaseUrl);
  });

  test("adds an app from an uploaded YAML spec", async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const name = `PW YAML ${Date.now()}`;
    const integrations = new AdminIntegrationsPage(page);
    const detail = new AdminIntegrationDetailPage(page);

    await integrations.goto();
    await integrations.openAdd("Custom API");
    await integrations.fillDetectedApi({
      name,
      spec: {
        fileName: "openapi.yaml",
        text: ticketsOpenApiYaml(name, upstream.apiBaseUrl),
      },
      detected: "REST API, 2 endpoints",
    });
    createdId = await integrations.submit();
    await detail.expectLoaded(name);
    await detail.openTab("Actions");
    await expect(
      detail.policyButton(TICKET_ACTIONS.read.summary, "Allow")
    ).toHaveAttribute("aria-pressed", "true");
    await expect(
      detail.policyButton(TICKET_ACTIONS.create.summary, "Ask")
    ).toHaveAttribute("aria-pressed", "true");
    await detail.openTab("Configuration");
    await detail.expectBaseUrl(upstream.apiBaseUrl);
  });
});
