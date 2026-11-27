import { expect, test } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { AdminIntegrationsPage } from "@tests/e2e/pages/AdminIntegrationsPage";
import { AdminIntegrationDetailPage } from "@tests/e2e/pages/AdminIntegrationDetailPage";
import { ApiAppUpstream } from "@tests/e2e/utils/apiAppUpstream";

const SCHEMA = `type Ticket { id: ID! title: String! }
type Query { ticket(id: ID!): Ticket }
type Mutation { ticketClose(id: ID!): Ticket }`;

test.describe("Custom GraphQL app", () => {
  let createdId: number | null = null;

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

  test("adds an app from an uploaded schema and shows its root fields", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const name = `PW GraphQL Tickets ${Date.now()}`;
    const integrations = new AdminIntegrationsPage(page);
    const detail = new AdminIntegrationDetailPage(page);

    await integrations.goto();
    await integrations.openAdd("Custom API");
    await integrations.fillDetectedApi({
      name,
      url: "https://tickets.example.com/graphql",
      spec: { fileName: "schema.graphql", text: SCHEMA },
      detected: "GraphQL API, 1 query and 1 mutation",
    });
    createdId = await integrations.submit();
    await detail.expectLoaded(name);

    await detail.openTab("Actions");
    await expect(detail.policyButton("ticket", "Allow")).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    await expect(detail.policyButton("ticketClose", "Ask")).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });

  test("adds an app from an endpoint that answers introspection", async ({
    page,
  }) => {
    const upstream = await ApiAppUpstream.start();
    try {
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const name = `PW GraphQL Introspection ${Date.now()}`;
      const integrations = new AdminIntegrationsPage(page);
      const detail = new AdminIntegrationDetailPage(page);

      await integrations.goto();
      await integrations.openAdd("Custom API");
      await integrations.fillDetectedApi({
        name,
        url: upstream.graphqlUrl,
        detected: "GraphQL API, 1 query and 1 mutation",
      });
      createdId = await integrations.submit();
      await detail.expectLoaded(name);

      await detail.openTab("Actions");
      await expect(detail.policyButton("ticket", "Allow")).toHaveAttribute(
        "aria-pressed",
        "true"
      );
      await expect(detail.policyButton("ticketClose", "Ask")).toHaveAttribute(
        "aria-pressed",
        "true"
      );
      expect(
        upstream.requests.some(
          (request) =>
            request.path === "/graphql" && request.body.includes("__schema")
        )
      ).toBe(true);
    } finally {
      await upstream.stop();
    }
  });
});
