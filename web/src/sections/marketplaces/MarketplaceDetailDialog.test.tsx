import {
  act,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import MarketplaceDetailDialog from "@/sections/marketplaces/MarketplaceDetailDialog";
import {
  detail,
  marketplace,
} from "@/sections/marketplaces/__fixtures__/marketplace";
import { SWR_KEYS } from "@/lib/swr-keys";

const url = SWR_KEYS.marketplace(marketplace.id);
const proposal = {
  revision: "commit-a",
  skill_ids: detail.skills.map((skill) => skill.id),
  approved: false,
};
const awaiting = {
  ...detail,
  marketplace: {
    ...marketplace,
    sync_requested: false,
    sync_pending: false,
    sync_status: "needs_confirmation",
    retirement_proposal: proposal,
  },
};
let fetchSpy: jest.SpiedFunction<typeof fetch>;
beforeEach(() => {
  fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(
      async (path) =>
        new Response(
          JSON.stringify(path === SWR_KEYS.buildExternalApps ? [] : awaiting)
        )
    );
});
afterEach(() => jest.restoreAllMocks());

it("revokes retirement review when a retained proposal is no longer awaiting confirmation", async () => {
  const user = setupUser();
  render(
    <MarketplaceDetailDialog
      open
      marketplaceId={marketplace.id}
      onClose={jest.fn()}
    />
  );
  await user.click(
    await screen.findByRole("button", { name: "Review retirements" })
  );
  fetchSpy.mockResolvedValue(
    new Response(
      JSON.stringify({
        ...awaiting,
        marketplace: { ...awaiting.marketplace, sync_status: "failed" },
      })
    )
  );
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "Confirm retirement" })
    ).not.toBeInTheDocument()
  );
  expect(
    screen.getByRole("button", { name: "Review retirements" })
  ).toBeDisabled();
  expect(fetchSpy.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
    false
  );
});

it("requires explicit review and sends exactly the displayed revision and skill IDs", async () => {
  const user = setupUser();
  render(
    <MarketplaceDetailDialog
      open
      marketplaceId={marketplace.id}
      onClose={jest.fn()}
    />
  );
  await user.click(
    await screen.findByRole("button", { name: "Review retirements" })
  );
  expect(screen.getByText("alpha")).toBeInTheDocument();
  expect(screen.getByText("commit-a")).toBeInTheDocument();
  expect(fetchSpy.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
    false
  );
  const pending = Promise.withResolvers<Response>();
  fetchSpy.mockImplementation(async (_path, init) =>
    init?.method === "POST"
      ? pending.promise
      : new Response(JSON.stringify({ ...detail, marketplace }))
  );
  await user.click(screen.getByRole("button", { name: "Confirm retirement" }));
  expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  expect(fetchSpy).toHaveBeenCalledWith(
    `${url}/confirm-retirements`,
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        revision: "commit-a",
        skill_ids: proposal.skill_ids,
      }),
    })
  );
  await act(async () =>
    pending.resolve(new Response(JSON.stringify(marketplace)))
  );
  expect(await screen.findByText("Sync requested")).toBeInTheDocument();
});

it("refreshes a changed proposal after rejection and requires review again", async () => {
  const user = setupUser();
  render(
    <MarketplaceDetailDialog
      open
      marketplaceId={marketplace.id}
      onClose={jest.fn()}
    />
  );
  await user.click(
    await screen.findByRole("button", { name: "Review retirements" })
  );
  const changed = {
    ...awaiting,
    marketplace: {
      ...awaiting.marketplace,
      retirement_proposal: { ...proposal, revision: "commit-b" },
    },
  };
  const refresh = Promise.withResolvers<Response>();
  fetchSpy.mockImplementation(async (_path, init) =>
    init?.method === "POST"
      ? new Response(
          JSON.stringify({ detail: "Retirement proposal changed" }),
          { status: 409 }
        )
      : refresh.promise
  );
  await user.click(screen.getByRole("button", { name: "Confirm retirement" }));
  expect(
    await screen.findByText("Retirement proposal changed")
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Confirm retirement" })
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Review retirements" })
  ).toBeDisabled();
  await act(async () => refresh.resolve(new Response(JSON.stringify(changed))));
  await user.click(
    await screen.findByRole("button", { name: "Review retirements" })
  );
  expect(await screen.findByText("commit-b")).toBeInTheDocument();
  expect(
    fetchSpy.mock.calls.filter(([, init]) => init?.method === "POST")
  ).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "Confirm retirement" }));
  await waitFor(() =>
    expect(fetchSpy).toHaveBeenCalledWith(
      `${url}/confirm-retirements`,
      expect.objectContaining({
        body: JSON.stringify({
          revision: "commit-b",
          skill_ids: proposal.skill_ids,
        }),
      })
    )
  );
});

it("never confirms retirements whose names are absent from detail", async () => {
  fetchSpy.mockResolvedValue(
    new Response(JSON.stringify({ ...awaiting, skills: [] }))
  );
  render(
    <MarketplaceDetailDialog
      open
      marketplaceId={marketplace.id}
      onClose={jest.fn()}
    />
  );
  expect(
    await screen.findByRole("button", { name: "Review retirements" })
  ).toBeDisabled();
  expect(screen.getByText(/skill names are unavailable/)).toBeInTheDocument();
});

it("confirms removal and allows cancellation before deleting", async () => {
  const user = setupUser();
  const onClose = jest.fn();
  render(
    <MarketplaceDetailDialog
      open
      marketplaceId={marketplace.id}
      onClose={onClose}
    />
  );
  await user.click(await screen.findByRole("button", { name: "Remove" }));
  expect(
    screen.getByText(/Remove Team tools and all its synced skills/)
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(
    fetchSpy.mock.calls.some(([, init]) => init?.method === "DELETE")
  ).toBe(false);
  await user.click(screen.getByRole("button", { name: "Remove" }));
  fetchSpy.mockResolvedValue(new Response("null"));
  await user.click(screen.getByRole("button", { name: "Confirm removal" }));
  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  expect(fetchSpy).toHaveBeenCalledWith(url, { method: "DELETE" });
});

it("explains login replacement and uses the current user's connection", async () => {
  const user = setupUser();
  render(
    <MarketplaceDetailDialog
      open
      marketplaceId={marketplace.id}
      onClose={jest.fn()}
    />
  );
  await user.click(
    await screen.findByRole("button", { name: "Replace login" })
  );
  expect(
    screen.getByText(/Use your current GitHub connection/)
  ).toBeInTheDocument();
  expect(fetchSpy.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
    false
  );
  fetchSpy.mockImplementation(
    async (_path, init) =>
      new Response(
        JSON.stringify(
          init?.method === "POST" ? marketplace : { ...detail, marketplace }
        )
      )
  );
  await user.click(screen.getByRole("button", { name: "Replace login" }));
  expect(await screen.findByText("Sync requested")).toBeInTheDocument();
  expect(fetchSpy).toHaveBeenCalledWith(`${url}/replace-login`, {
    method: "POST",
  });
});

it("shows blocked entries and queues manual sync without claiming completion", async () => {
  const user = setupUser();
  fetchSpy.mockResolvedValue(
    new Response(
      JSON.stringify({
        ...detail,
        marketplace: {
          ...marketplace,
          sync_requested: false,
          sync_pending: false,
          blocked_entries: { broken: "Invalid skill bundle" },
        },
      })
    )
  );
  render(
    <MarketplaceDetailDialog
      open
      marketplaceId={marketplace.id}
      onClose={jest.fn()}
    />
  );
  expect(await screen.findByText("Invalid skill bundle")).toBeInTheDocument();
  fetchSpy.mockImplementation(
    async (_path, init) =>
      new Response(
        JSON.stringify(
          init?.method === "POST" ? marketplace : { ...detail, marketplace }
        )
      )
  );
  await user.click(screen.getByRole("button", { name: "Sync now" }));
  expect(await screen.findByText("Sync requested")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Sync now" })).toBeDisabled();
  expect(fetchSpy).toHaveBeenCalledWith(`${url}/sync`, { method: "POST" });
});

it("handles unauthorized detail and retries without showing mutation actions", async () => {
  const user = setupUser();
  fetchSpy.mockResolvedValue(
    new Response(JSON.stringify({ detail: "Permission removed" }), {
      status: 403,
    })
  );
  render(
    <MarketplaceDetailDialog
      open
      marketplaceId={marketplace.id}
      onClose={jest.fn()}
    />
  );
  expect(
    await screen.findByText("You do not have access to these marketplaces.")
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Sync now" })
  ).not.toBeInTheDocument();
  fetchSpy.mockResolvedValue(new Response(JSON.stringify(awaiting)));
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  expect(await screen.findByText("Team tools")).toBeInTheDocument();
});

it("requires a fresh review when a refresh changes the displayed proposal", async () => {
  const user = setupUser();
  render(
    <MarketplaceDetailDialog
      open
      marketplaceId={marketplace.id}
      onClose={jest.fn()}
    />
  );
  await user.click(
    await screen.findByRole("button", { name: "Review retirements" })
  );
  fetchSpy.mockResolvedValue(
    new Response(
      JSON.stringify({
        ...awaiting,
        marketplace: {
          ...awaiting.marketplace,
          retirement_proposal: { ...proposal, revision: "commit-b" },
        },
      })
    )
  );
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  expect(
    await screen.findByText(
      "The proposal changed. Review the latest proposal before confirming."
    )
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Confirm retirement" })
  ).not.toBeInTheDocument();
  expect(screen.getByText("commit-a")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Review retirements" }));
  expect(screen.getByText("commit-b")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Confirm retirement" })
  ).toBeEnabled();
  expect(fetchSpy.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
    false
  );
});
