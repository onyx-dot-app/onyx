/**
 * Every edit / delete control a scoped group manager should and shouldn't be offered.
 *
 * The recurring failure in this area is a split between the two halves of a decision:
 * the route authorizes the action while the projection still stamps it admin-only, so
 * the control never renders and the capability may as well not exist. Each assertion
 * here is the UI half of a rule the integration suite pins on the backend.
 */

import { worldTest as test, expect, actAsManager } from "./fixtures";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { AdminConnectorDetailPage } from "@tests/e2e/pages/AdminConnectorDetailPage";
import { AdminDocumentSetsPage } from "@tests/e2e/pages/AdminDocumentSetsPage";

// seeding a whole scoped world plus several re-logins puts these well past the
// default budget; the work is real, not a hang
test.describe.configure({ timeout: 240_000 });

test.describe("scoped manager affordances", () => {
  test("connector detail renders for a resource in no group", async ({
    page,
    world,
  }) => {
    await actAsManager(page, world.manager);
    const detail = new AdminConnectorDetailPage(page);

    await detail.goto(world.grouplessCcPairId);
    await detail.expectLoaded();
  });

  test("delete is offered on the groupless connector, not the shared one", async ({
    page,
    world,
  }) => {
    await actAsManager(page, world.manager);
    const detail = new AdminConnectorDetailPage(page);

    await detail.goto(world.managedCcPairId);
    await detail.openManageMenu();
    await detail.expectDeleteOffered(false);

    await detail.goto(world.grouplessCcPairId);
    await detail.openManageMenu();
    await detail.expectDeleteOffered(true);
  });

  test("a connector in an unmanaged group is not reachable", async ({
    page,
    world,
  }) => {
    await actAsManager(page, world.manager);
    const detail = new AdminConnectorDetailPage(page);

    await detail.goto(world.foreignCcPairId);
    await detail.expectNotAccessible();
  });

  test("both document sets stay editable, only the groupless one deletable", async ({
    page,
    world,
  }) => {
    await actAsManager(page, world.manager);
    const documentSets = new AdminDocumentSetsPage(page);
    await documentSets.goto();

    await documentSets.expectListed(world.managedDocSetName);
    await documentSets.expectListed(world.grouplessDocSetName);
    await documentSets.expectDeleteOffered(world.managedDocSetName, false);
    await documentSets.expectDeleteOffered(world.grouplessDocSetName, true);

    // navigating away last — it leaves the list page
    await documentSets.expectEditable(
      world.grouplessDocSetName,
      world.grouplessDocSetId
    );
  });

  test("actions list shows own and agent-connected, not the orphan", async ({
    page,
    world,
  }) => {
    const managerClient = await actAsManager(page, world.manager);
    const visible = await managerClient.listOpenApiTools();
    const ids = new Set(visible.map((tool) => tool.id));

    expect(ids.has(world.ownActionId)).toBe(true);
    expect(ids.has(world.connectedActionId)).toBe(true);
    expect(ids.has(world.orphanActionId)).toBe(false);

    await page.goto(ADMIN_ROUTES.OPENAPI_ACTIONS.path);
    await expect(
      page.getByText(`orphan-action-`, { exact: false })
    ).toHaveCount(0);
  });
});
