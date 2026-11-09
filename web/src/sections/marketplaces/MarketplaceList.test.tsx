import {
  act,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import MarketplaceList from "@/sections/marketplaces/MarketplaceList";
import {
  detail,
  marketplace,
} from "@/sections/marketplaces/__fixtures__/marketplace";
import { useUser } from "@/providers/UserProvider";
import { Permission } from "@/lib/types";

jest.mock("@/providers/UserProvider", () => ({ useUser: jest.fn() }));
const actualUseUser = jest.requireActual<
  typeof import("@/providers/UserProvider")
>("@/providers/UserProvider").useUser;

import { SWR_KEYS } from "@/lib/swr-keys";

let fetchSpy: jest.SpiedFunction<typeof fetch>;
beforeEach(() => {
  jest.mocked(useUser).mockImplementation(actualUseUser);
  fetchSpy = jest.spyOn(global, "fetch");
});
afterEach(() => {
  jest.restoreAllMocks();
  jest.useRealTimers();
});

it("fetches shared sources locally and opens the real detail dialog", async () => {
  const user = setupUser();
  fetchSpy.mockImplementation(
    async (url) =>
      new Response(
        JSON.stringify(url === SWR_KEYS.marketplaces ? [marketplace] : detail)
      )
  );
  render(<MarketplaceList />);
  await user.click(
    await screen.findByRole("button", { name: "View details for Team tools" })
  );
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  expect(await screen.findByText("alpha")).toBeInTheDocument();
  expect(fetchSpy).toHaveBeenCalledWith(SWR_KEYS.marketplace(marketplace.id));
});

it("renders loading, empty state and the host sync action", async () => {
  const user = setupUser();
  const pending = Promise.withResolvers<Response>();
  fetchSpy.mockReturnValue(pending.promise);
  const onSyncFromGitHub = jest.fn();
  render(<MarketplaceList onSyncFromGitHub={onSyncFromGitHub} />);
  expect(screen.queryByText("No marketplaces yet")).not.toBeInTheDocument();
  await act(async () => pending.resolve(new Response("[]")));
  expect(await screen.findByText("No marketplaces yet")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Sync from GitHub" }));
  expect(onSyncFromGitHub).toHaveBeenCalledTimes(1);
});

it("allows a host kind filter and hides counts that the API cannot supply", async () => {
  fetchSpy.mockResolvedValue(
    new Response(
      JSON.stringify([
        marketplace,
        {
          ...marketplace,
          id: "40000000-0000-4000-8000-000000000004",
          name: "Excluded source",
        },
      ])
    )
  );
  render(
    <MarketplaceList
      filter={(row) => row.id === marketplace.id}
      getCountLabel={() => null}
    />
  );
  expect(await screen.findByText("Team tools")).toBeInTheDocument();
  expect(screen.queryByText("Excluded source")).not.toBeInTheDocument();
  expect(screen.queryByText(/active skills/)).not.toBeInTheDocument();
});

it.each([403, 500])(
  "shows server errors and retries a %s response",
  async (status) => {
    const user = setupUser();
    fetchSpy.mockResolvedValue(
      new Response(JSON.stringify({ detail: "Cannot read sources" }), {
        status,
      })
    );
    render(<MarketplaceList />);
    expect(await screen.findByText("Cannot read sources")).toBeInTheDocument();
    expect(
      screen.getByText(
        status === 403
          ? "You do not have access to these marketplaces."
          : "Could not load marketplaces"
      )
    ).toBeInTheDocument();
    fetchSpy.mockResolvedValue(new Response("[]"));
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("No marketplaces yet")).toBeInTheDocument();
  }
);

it("polls queued and claimed work while visible and stops after completion", async () => {
  jest.useFakeTimers();
  fetchSpy.mockResolvedValue(new Response(JSON.stringify([marketplace])));
  const visibility = jest
    .spyOn(document, "visibilityState", "get")
    .mockReturnValue("visible");
  const onChanged = jest.fn();
  const view = render(<MarketplaceList onChanged={onChanged} />);
  expect(await screen.findByText("Sync pending")).toBeInTheDocument();
  const initialReads = fetchSpy.mock.calls.length;
  visibility.mockReturnValue("hidden");
  await act(async () => {
    await jest.advanceTimersByTimeAsync(3100);
  });
  expect(fetchSpy).toHaveBeenCalledTimes(initialReads);
  visibility.mockReturnValue("visible");
  fetchSpy.mockResolvedValue(
    new Response(
      JSON.stringify([
        { ...marketplace, sync_requested: false, sync_pending: true },
      ])
    )
  );
  await act(async () => {
    await jest.advanceTimersByTimeAsync(3100);
  });
  expect(await screen.findByText("Sync pending")).toBeInTheDocument();
  expect(fetchSpy.mock.calls.length).toBeGreaterThan(initialReads);
  expect(onChanged).not.toHaveBeenCalled();
  fetchSpy.mockResolvedValue(
    new Response(
      JSON.stringify([
        {
          ...marketplace,
          sync_requested: false,
          sync_pending: false,
          sync_status: "applied",
        },
      ])
    )
  );
  await act(async () => {
    await jest.advanceTimersByTimeAsync(3100);
  });
  expect(await screen.findByText("Applied")).toBeInTheDocument();
  expect(onChanged).toHaveBeenCalledTimes(1);
  view.rerender(<MarketplaceList onChanged={() => onChanged()} />);
  const appliedReads = fetchSpy.mock.calls.length;
  await act(async () => {
    await jest.advanceTimersByTimeAsync(9000);
  });
  expect(fetchSpy).toHaveBeenCalledTimes(appliedReads);
  expect(onChanged).toHaveBeenCalledTimes(1);
  expect(
    fetchSpy.mock.calls.every(
      ([, init]) => !init?.method || init.method === "GET"
    )
  ).toBe(true);
});

it("does not fetch on a hidden host tab", async () => {
  fetchSpy.mockResolvedValue(new Response("[]"));
  const view = render(<MarketplaceList visible={false} />);
  expect(fetchSpy).not.toHaveBeenCalled();
  view.rerender(<MarketplaceList visible />);
  await waitFor(() =>
    expect(fetchSpy).toHaveBeenCalledWith(SWR_KEYS.marketplaces)
  );
});

it("closes source detail before opening company access controls", async () => {
  jest.mocked(useUser).mockImplementation(() => ({
    ...actualUseUser(),
    permissions: [Permission.MANAGE_SKILLS],
  }));
  const company = { ...marketplace, owner_user_id: null };
  fetchSpy.mockImplementation(
    async (url) =>
      new Response(
        JSON.stringify(
          url === SWR_KEYS.marketplaces
            ? [company]
            : { ...detail, marketplace: company }
        )
      )
  );
  const onConfigureAccess = jest.fn();
  render(<MarketplaceList onConfigureAccess={onConfigureAccess} />);
  const user = setupUser();
  await user.click(
    await screen.findByRole("button", { name: "View details for Team tools" })
  );
  await user.click(
    await screen.findByRole("button", { name: "Configure access" })
  );
  expect(onConfigureAccess).toHaveBeenCalledWith(company);
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  );
});

it("forgets source detail when its host tab is hidden", async () => {
  const user = setupUser();
  fetchSpy.mockImplementation(
    async (url) =>
      new Response(
        JSON.stringify(url === SWR_KEYS.marketplaces ? [marketplace] : detail)
      )
  );
  const view = render(<MarketplaceList />);
  await user.click(
    await screen.findByRole("button", { name: "View details for Team tools" })
  );
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  view.rerender(<MarketplaceList visible={false} />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  view.rerender(<MarketplaceList visible />);
  await screen.findByRole("button", { name: "View details for Team tools" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "View details for Team tools" })
  );
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
});

it("refreshes host Skills once after removing a source", async () => {
  const user = setupUser();
  let removed = false;
  fetchSpy.mockImplementation(async (url, init) => {
    if (init?.method === "DELETE") {
      removed = true;
      return new Response("null");
    }
    return new Response(
      JSON.stringify(
        url === SWR_KEYS.marketplaces ? (removed ? [] : [marketplace]) : detail
      )
    );
  });
  const onChanged = jest.fn();
  render(<MarketplaceList onChanged={onChanged} />);
  await user.click(
    await screen.findByRole("button", { name: "View details for Team tools" })
  );
  await user.click(await screen.findByRole("button", { name: "Remove" }));
  await user.click(screen.getByRole("button", { name: "Confirm removal" }));
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  );
  expect(await screen.findByText("No marketplaces yet")).toBeInTheDocument();
  expect(onChanged).toHaveBeenCalledTimes(1);
});
