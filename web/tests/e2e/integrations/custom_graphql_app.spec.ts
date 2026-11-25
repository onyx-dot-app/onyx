import { expect, test } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { AdminIntegrationsPage } from "@tests/e2e/pages/AdminIntegrationsPage";
import { AdminIntegrationDetailPage } from "@tests/e2e/pages/AdminIntegrationDetailPage";

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
    await integrations.fillGraphQLApi({
      name,
      endpointUrl: "https://tickets.example.com/graphql",
      schema: SCHEMA,
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
});
