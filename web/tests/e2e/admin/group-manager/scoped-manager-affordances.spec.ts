/**
 * Every edit / delete control a scoped group manager should and shouldn't be offered.
 *
 * The recurring failure in this area is a split between the two halves of a decision:
 * the route authorizes the action while the projection still stamps it admin-only, so
 * the control never renders and the capability may as well not exist. Each assertion
 * here is the UI half of a rule the integration suite pins on the backend.
 */

import { worldTest as test, expect, actAsManager } from "./fixtures";
import { AdminConnectorDetailPage } from "@tests/e2e/pages/AdminConnectorDetailPage";
import { AdminDocumentSetsPage } from "@tests/e2e/pages/AdminDocumentSetsPage";
import { IndexingStatusPage } from "@tests/e2e/admin/connector/IndexingStatusPage";

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

  test("delete is offered on the Editor connector and the groupless one", async ({
    page,
    world,
  }) => {
    await actAsManager(page, world.manager);
    const detail = new AdminConnectorDetailPage(page);

    // the managed group is an Editor on this connector, and Editors may delete
    await detail.goto(world.managedCcPairId);
    await detail.openManageMenu();
    await detail.expectDeleteOffered(true);

    await detail.goto(world.grouplessCcPairId);
    await detail.openManageMenu();
    await detail.expectDeleteOffered(true);
  });

  test("indexing status links only the rows the manager can manage", async ({
    page,
    world,
  }) => {
    await actAsManager(page, world.manager);
    const status = new IndexingStatusPage(page);

    await status.goto();
    await status.waitForConnector(world.publicCcPairName);

    await status.expectRowInert(world.publicCcPairName);
    await status.expectRowOpens(world.managedCcPairName, world.managedCcPairId);
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

  test("actions list offers edit only on the manager's own action", async ({
    page,
    world,
  }) => {
    const managerClient = await actAsManager(page, world.manager);
    const visible = await managerClient.listOpenApiTools();
    const editable = new Map(
      visible.map((tool) => [tool.id, tool.permissions.edit === true])
    );

    // a scoped manager manages only the integrations in its own "My uploads"
    expect(editable.get(world.ownActionId)).toBe(true);
    // Organization library integrations reach every member, read-only here
    expect(editable.get(world.connectedActionId)).toBe(false);
    expect(editable.get(world.orphanActionId)).toBe(false);
  });
});
