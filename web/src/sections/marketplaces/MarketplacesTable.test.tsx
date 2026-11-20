import { PointerEventsCheckLevel } from "@testing-library/user-event";
import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { mockFetch, requestBody } from "@tests/setup/integrationTestUtils";
import { toast } from "@opal/layouts";
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
    [`POST ${DETAIL_URL}/sync`]: detailFixture({ syncing: true }),
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

test("a running sync disables Sync now", async () => {
  mockFetch({
    "/api/marketplaces": { marketplaces: [summaryFixture({ syncing: true })] },
  });
  render(<MarketplacesTable />);
  const actor = user();

  expect(await screen.findByText("Syncing")).toBeInTheDocument();
  await actor.click(
    screen.getByRole("button", { name: "Actions for acme/plugins" })
  );
  expect(
    await screen.findByRole("menuitem", { name: /Sync now/ })
  ).toHaveAttribute("aria-disabled", "true");
});

test("a marketplace that never synced offers Sync now", async () => {
  mockFetch({
    "/api/marketplaces": {
      marketplaces: [
        summaryFixture({ last_synced_at: null, last_synced_revision: null }),
      ],
    },
  });
  render(<MarketplacesTable />);
  const actor = user();

  expect(await screen.findByText("Not synced")).toBeInTheDocument();
  await actor.click(
    screen.getByRole("button", { name: "Actions for acme/plugins" })
  );
  expect(
    await screen.findByRole("menuitem", { name: /Sync now/ })
  ).not.toHaveAttribute("aria-disabled", "true");
});

test("Remove names the plugins that it deletes before it asks to confirm", async () => {
  const fetchMock = mockFetch({
    "/api/marketplaces": { marketplaces: [summaryFixture()] },
    [DETAIL_URL]: detailFixture(),
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

test("Remove stays disabled when the plugin list does not load", async () => {
  mockFetch({
    "/api/marketplaces": { marketplaces: [summaryFixture()] },
    [DETAIL_URL]: new Response(JSON.stringify({ detail: "boom" }), {
      status: 500,
    }),
  });
  render(<MarketplacesTable />);

  await user().click(
    await screen.findByRole("button", { name: "Actions for acme/plugins" })
  );
  await user().click(await screen.findByRole("menuitem", { name: /Remove/ }));

  expect(
    await screen.findByText("Could not load the plugins of this marketplace.")
  ).toBeInTheDocument();
  expect(screen.queryByText("This marketplace has no plugins.")).toBeNull();
  expect(screen.getByRole("button", { name: "Remove" })).toBeDisabled();
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

test("a member sees a company marketplace with no actions", async () => {
  mockFetch({
    "/api/marketplaces": {
      marketplaces: [summaryFixture({ scope: "company", can_manage: false })],
    },
  });
  render(<MarketplacesTable />);

  const table = await screen.findByRole("table", { name: "Marketplaces" });
  expect(within(table).getByText("Company")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Actions for acme/plugins" })
  ).not.toBeInTheDocument();
});

test("Replace login warns when the new login has no GitHub connection", async () => {
  mockFetch({
    "/api/marketplaces": { marketplaces: [summaryFixture()] },
    [`POST ${DETAIL_URL}/replace-login`]: detailFixture({
      login_has_github: false,
    }),
  });
  const warning = jest.spyOn(toast, "warning").mockReturnValue("toast-id");
  render(<MarketplacesTable />);
  const actor = user();

  await actor.click(
    await screen.findByRole("button", { name: "Actions for acme/plugins" })
  );
  await actor.click(
    await screen.findByRole("menuitem", { name: /Replace login/ })
  );
  await waitFor(() =>
    expect(warning).toHaveBeenCalledWith(
      expect.stringContaining("you have not connected GitHub")
    )
  );
});
