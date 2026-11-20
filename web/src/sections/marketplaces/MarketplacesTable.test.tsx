import { PointerEventsCheckLevel } from "@testing-library/user-event";
import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { mockFetch, requestBody } from "@tests/setup/integrationTestUtils";
import MarketplacesTable from "@/sections/marketplaces/MarketplacesTable";
import {
  MARKETPLACE_ID,
  detailFixture,
  summaryFixture,
} from "@/sections/marketplaces/__fixtures__/marketplace";

const DETAIL_URL = `/api/marketplaces/${MARKETPLACE_ID}`;

function user() {
  return setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
}

afterEach(() => jest.restoreAllMocks());

test("lists each marketplace with its source, plugins and sync", async () => {
  mockFetch({
    "/api/marketplaces": {
      marketplaces: [
        summaryFixture({ ref: "v2", folder: "catalog", scope: "company" }),
      ],
    },
  });
  render(<MarketplacesTable />);

  const table = await screen.findByRole("table", { name: "Marketplaces" });
  expect(
    within(table).getByText("acme/plugins/catalog@v2")
  ).toBeInTheDocument();
  expect(within(table).getByText("Company")).toBeInTheDocument();
  expect(within(table).getByText("2 plugins")).toBeInTheDocument();
  expect(within(table).getByText("Synced")).toBeInTheDocument();
  expect(within(table).getByText(/^Last sync /)).toBeInTheDocument();
});

test("a failed sync shows its reason and offers Sync now", async () => {
  const error = "The GitHub connection of me@example.com is gone.";
  const fetchMock = mockFetch({
    "/api/marketplaces": {
      marketplaces: [summaryFixture({ last_error: error })],
    },
    [`POST ${DETAIL_URL}/sync`]: detailFixture({ sync_requested: true }),
  });
  render(<MarketplacesTable />);

  expect(
    await screen.findByText("The last sync of acme/plugins failed")
  ).toBeInTheDocument();
  expect(screen.getAllByText(error).length).toBeGreaterThan(0);
  expect(screen.getByText("Sync failed")).toBeInTheDocument();

  await user().click(screen.getByRole("button", { name: "Sync now" }));
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) => url === `${DETAIL_URL}/sync` && init?.method === "POST"
      )
    ).toBe(true)
  );
});

test("held deletes ask the user to review and confirm them", async () => {
  const revision = "c".repeat(40);
  const fetchMock = mockFetch({
    "/api/marketplaces": {
      marketplaces: [summaryFixture({ needs_confirmation: true })],
    },
    [DETAIL_URL]: detailFixture({
      needs_confirmation: true,
      pending_delete_revision: revision,
      pending_deletes: [
        {
          plugin_id: "33333333-3333-4333-8333-333333333333",
          entry_key: "review-kit",
          name: "review-kit",
        },
      ],
    }),
    [`POST ${DETAIL_URL}/confirm-deletes`]: detailFixture(),
  });
  render(<MarketplacesTable />);

  await user().click(
    await screen.findByRole("button", { name: "Review deletes" })
  );
  const dialog = await screen.findByRole("dialog");
  const list = await within(dialog).findByRole("list", {
    name: "Plugins to delete",
  });
  expect(within(list).getByText("review-kit")).toBeInTheDocument();

  await user().click(
    within(dialog).getByRole("button", { name: "Delete 1 plugin" })
  );
  await waitFor(() =>
    expect(
      requestBody(fetchMock, "POST", `${DETAIL_URL}/confirm-deletes`)
    ).toEqual({ revision })
  );
});

test("Remove names the plugins that it deletes before it asks to confirm", async () => {
  const fetchMock = mockFetch({
    "/api/marketplaces": { marketplaces: [summaryFixture()] },
    [DETAIL_URL]: detailFixture({
      pending_delete_revision: "c".repeat(40),
      pending_deletes: [
        {
          plugin_id: "55555555-5555-4555-8555-555555555555",
          entry_key: "old-kit",
          name: "old-kit",
        },
      ],
    }),
    [`DELETE ${DETAIL_URL}`]: new Response("null"),
  });
  render(<MarketplacesTable />);

  await user().click(
    await screen.findByRole("button", { name: "Actions for acme/plugins" })
  );
  await user().click(await screen.findByRole("menuitem", { name: /Remove/ }));

  const list = await screen.findByRole("list", { name: "Plugins to delete" });
  expect(within(list).getByText("review-kit")).toBeInTheDocument();
  expect(within(list).getByText("plan-kit")).toBeInTheDocument();
  expect(within(list).getByText("old-kit")).toBeInTheDocument();
  expect(within(list).queryByText("npm-kit")).not.toBeInTheDocument();

  await user().click(screen.getByRole("button", { name: "Remove" }));
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) => url === DETAIL_URL && init?.method === "DELETE"
      )
    ).toBe(true)
  );
});

test("the default access item shows only for a company marketplace", async () => {
  const fetchMock = mockFetch({
    "/api/marketplaces": {
      marketplaces: [summaryFixture({ scope: "company" })],
    },
    [`PUT ${DETAIL_URL}/default-access`]: detailFixture({
      scope: "company",
      default_installation_policy: "DEFAULT",
    }),
  });
  render(<MarketplacesTable />);
  const actor = user();

  await actor.click(
    await screen.findByRole("button", { name: "Actions for acme/plugins" })
  );
  await actor.click(
    await screen.findByRole("menuitem", { name: /Default Access/ })
  );
  const dialog = await screen.findByRole("dialog");
  await actor.click(
    within(dialog).getByRole("combobox", { name: "Default Access" })
  );
  await actor.click(await screen.findByRole("option", { name: /^Installed/ }));
  await actor.click(within(dialog).getByRole("button", { name: "Save" }));

  await waitFor(() =>
    expect(
      requestBody(fetchMock, "PUT", `${DETAIL_URL}/default-access`)
    ).toEqual({ installation_policy: "DEFAULT" })
  );
});
