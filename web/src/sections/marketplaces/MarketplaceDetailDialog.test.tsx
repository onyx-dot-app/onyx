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

const retiredSkill = {
  id: "50000000-0000-4000-8000-000000000005",
  name: "old-alpha",
  current_version_id: null,
  retired_at: "2026-11-08T12:00:00Z",
  follows_marketplace_access: true,
};
const withRetired = {
  ...detail,
  marketplace: {
    ...marketplace,
    sync_requested: false,
    sync_pending: false,
    live_skill_count: 1,
    retired_skill_count: 1,
  },
  skills: [...detail.skills, retiredSkill],
};
const withoutRetired = {
  ...withRetired,
  marketplace: { ...withRetired.marketplace, retired_skill_count: 0 },
  skills: detail.skills,
};
const deleteUrl = `/api/skills/custom/${retiredSkill.id}`;

it("offers only deletion for a retired skill and requires confirmation", async () => {
  fetchSpy.mockResolvedValue(new Response(JSON.stringify(withRetired)));
  const user = setupUser();
  const onClose = jest.fn();
  const onChanged = jest.fn();
  render(
    <MarketplaceDetailDialog
      open
      marketplaceId={marketplace.id}
      onClose={onClose}
      onChanged={onChanged}
    />
  );
  expect(await screen.findByText("Retired")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Delete alpha" })
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Delete old-alpha" }));
  expect(
    screen.getByText(/Permanently delete old-alpha and its version history/)
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(
    fetchSpy.mock.calls.some(([, init]) => init?.method === "DELETE")
  ).toBe(false);
  await user.click(screen.getByRole("button", { name: "Delete old-alpha" }));
  const pending = Promise.withResolvers<Response>();
  fetchSpy.mockImplementation(async (path, init) =>
    init?.method === "DELETE"
      ? pending.promise
      : new Response(
          JSON.stringify(
            path === SWR_KEYS.marketplaces
              ? [withoutRetired.marketplace]
              : withoutRetired
          )
        )
  );
  await user.click(screen.getByRole("button", { name: "Delete" }));
  expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  await user.keyboard("{Escape}{Escape}");
  expect(onClose).not.toHaveBeenCalled();
  expect(
    fetchSpy.mock.calls.filter(([, init]) => init?.method === "DELETE")
  ).toHaveLength(1);
  expect(fetchSpy).toHaveBeenCalledWith(deleteUrl, { method: "DELETE" });
  await act(async () => pending.resolve(new Response(null, { status: 204 })));
  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  expect(screen.queryByText("old-alpha")).not.toBeInTheDocument();
  expect(screen.getByText("alpha")).toBeInTheDocument();
  expect(screen.queryByText("Retired")).not.toBeInTheDocument();
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(onClose).not.toHaveBeenCalled();
});

it("keeps a refused deletion visible for retry without removing the row", async () => {
  fetchSpy.mockImplementation(async (_path, init) =>
    init?.method === "DELETE"
      ? new Response(
          JSON.stringify({ detail: "You can no longer delete this skill." }),
          { status: 403 }
        )
      : new Response(JSON.stringify(withRetired))
  );
  const user = setupUser();
  const onChanged = jest.fn();
  render(
    <MarketplaceDetailDialog
      open
      marketplaceId={marketplace.id}
      onClose={jest.fn()}
      onChanged={onChanged}
    />
  );
  await user.click(
    await screen.findByRole("button", { name: "Delete old-alpha" })
  );
  await user.click(screen.getByRole("button", { name: "Delete" }));
  expect(
    await screen.findByText("You can no longer delete this skill.")
  ).toBeInTheDocument();
  expect(screen.getByText(/Permanently delete old-alpha/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Delete" })).toBeEnabled();
  expect(onChanged).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(
    await screen.findByRole("button", { name: "Delete old-alpha" })
  ).toBeEnabled();
});

it("disables stale deletion after a refresh removes the selected skill", async () => {
  fetchSpy.mockResolvedValue(new Response(JSON.stringify(withRetired)));
  const user = setupUser();
  render(
    <MarketplaceDetailDialog
      open
      marketplaceId={marketplace.id}
      onClose={jest.fn()}
    />
  );
  await user.click(
    await screen.findByRole("button", { name: "Delete old-alpha" })
  );
  fetchSpy.mockResolvedValue(new Response(JSON.stringify(withoutRetired)));
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled()
  );
  expect(
    fetchSpy.mock.calls.some(([, init]) => init?.method === "DELETE")
  ).toBe(false);
});

it("reads and previews retired history without offering restore", async () => {
  const versionId = "60000000-0000-4000-8000-000000000006";
  fetchSpy.mockImplementation(async (path) => {
    if (path === SWR_KEYS.skillVersions(retiredSkill.id))
      return new Response(
        JSON.stringify([
          {
            id: versionId,
            version_number: 1,
            created_at: retiredSkill.retired_at,
            created_by: null,
            is_current: true,
            has_bundle: true,
            marketplace_revision: "commit-old",
          },
        ])
      );
    if (path === SWR_KEYS.skillVersion(retiredSkill.id, versionId))
      return new Response(
        JSON.stringify({
          name: retiredSkill.name,
          description: "Earlier skill",
          instructions_markdown: "Preserved instructions",
          files: [],
        })
      );
    return new Response(JSON.stringify(withRetired));
  });
  const user = setupUser();
  render(
    <MarketplaceDetailDialog
      open
      marketplaceId={marketplace.id}
      onClose={jest.fn()}
    />
  );
  await user.click(await screen.findByRole("button", { name: "Versions" }));
  expect(screen.getByRole("dialog")).toHaveAccessibleName(retiredSkill.name);
  expect(screen.queryByText(marketplace.name)).not.toBeInTheDocument();
  await user.click(
    await screen.findByRole("button", { name: "Preview version 1" })
  );
  expect(await screen.findByText("Preserved instructions")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Back" })).toBeEnabled();
  expect(
    screen.getByRole("button", { name: "Back to marketplace" })
  ).toBeEnabled();
  expect(
    screen.queryByRole("button", { name: /Restore/ })
  ).not.toBeInTheDocument();
  expect(fetchSpy.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
    false
  );
  await user.click(screen.getByRole("button", { name: "Back" }));
  expect(
    await screen.findByRole("button", { name: "Preview version 1" })
  ).toBeEnabled();
  await user.click(screen.getByRole("button", { name: "Back to marketplace" }));
  expect(screen.getByRole("dialog")).toHaveAccessibleName(
    "Marketplace details"
  );
});

function jsonResponse(data: object, init?: ResponseInit): Response {
  return new Response(JSON.stringify(data), init);
}

const pushSource = {
  ...marketplace,
  sync_requested: false,
  sync_pending: false,
  webhook_available: true,
  webhook_ref: "refs/heads/main",
};

it("enables push updates without claiming a sync, and locks actions during setup", async () => {
  const user = setupUser();
  const pending = Promise.withResolvers<Response>();
  let current = pushSource;
  // GET detail, POST setup, then GET updated detail.
  fetchSpy.mockImplementation(async (path, init) => {
    if (path === `${url}/webhook` && init?.method === "POST")
      return pending.promise;
    return jsonResponse({ ...detail, marketplace: current });
  });
  const onClose = jest.fn();
  render(
    <MarketplaceDetailDialog
      open
      marketplaceId={marketplace.id}
      onClose={onClose}
    />
  );
  await user.click(
    await screen.findByRole("button", { name: "Enable push updates" })
  );
  expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Sync now" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
  expect(screen.queryByText("Push updates configured")).not.toBeInTheDocument();
  current = { ...pushSource, webhook_enabled: true };
  await act(async () => pending.resolve(jsonResponse(current)));
  expect(
    await screen.findByText("Push updates configured")
  ).toBeInTheDocument();
  expect(
    screen.getByText("Waiting for the first verified delivery")
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Refresh push setup" })
  ).toBeEnabled();
  expect(screen.queryByText("Sync requested")).not.toBeInTheDocument();
  expect(onClose).not.toHaveBeenCalled();
  expect(fetchSpy).toHaveBeenCalledWith(`${url}/webhook`, { method: "POST" });
});

it.each([401, 403, 502])(
  "keeps manual sync and setup retry after a provider error (%s)",
  async (status) => {
    const user = setupUser();
    // GET detail succeeds; only GitHub setup fails.
    fetchSpy.mockImplementation(async (path, init) => {
      if (path === `${url}/webhook` && init?.method === "POST") {
        return jsonResponse(
          { detail: "Reconnect GitHub with repository admin access." },
          { status }
        );
      }
      if (path === `${url}/sync`) return jsonResponse(marketplace);
      return jsonResponse({ ...detail, marketplace: pushSource });
    });
    render(
      <MarketplaceDetailDialog
        open
        marketplaceId={marketplace.id}
        onClose={jest.fn()}
      />
    );
    await user.click(
      await screen.findByRole("button", { name: "Enable push updates" })
    );
    expect(
      await screen.findByText("Reconnect GitHub with repository admin access.")
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Enable push updates" })
    ).toBeEnabled();
    expect(
      screen.queryByText("Push updates configured")
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sync now" }));
    expect(fetchSpy).toHaveBeenCalledWith(`${url}/sync`, { method: "POST" });
  }
);

it("shows verified delivery time and refreshes registration", async () => {
  const user = setupUser();
  const configured = {
    ...pushSource,
    webhook_enabled: true,
    webhook_last_delivery_at: "2026-11-08T12:30:00Z",
  };
  // GET detail and POST setup both return persisted registration state.
  fetchSpy.mockImplementation(async (_path, init) =>
    jsonResponse(
      init?.method === "POST"
        ? configured
        : { ...detail, marketplace: configured }
    )
  );
  render(
    <MarketplaceDetailDialog
      open
      marketplaceId={marketplace.id}
      onClose={jest.fn()}
    />
  );
  expect(await screen.findByText(/Last verified delivery:/)).toHaveTextContent(
    "2026"
  );
  expect(screen.getByText("refs/heads/main")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Refresh push setup" }));
  expect(fetchSpy).toHaveBeenCalledWith(`${url}/webhook`, { method: "POST" });
});

it("offers manual sync without push setup when the provider reports no support", async () => {
  fetchSpy.mockResolvedValue(
    jsonResponse({
      ...detail,
      marketplace: { ...pushSource, webhook_available: false },
    })
  );
  render(
    <MarketplaceDetailDialog
      open
      marketplaceId={marketplace.id}
      onClose={jest.fn()}
    />
  );
  expect(await screen.findByRole("button", { name: "Sync now" })).toBeEnabled();
  expect(
    screen.queryByRole("button", { name: "Enable push updates" })
  ).not.toBeInTheDocument();
});
