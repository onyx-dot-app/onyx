import { FetchError, fetchErrorDetail } from "@/lib/fetcher";
import {
  confirmMarketplaceRetirements,
  createMarketplace,
  getMarketplace,
  listMarketplaces,
  previewMarketplace,
  removeMarketplace,
  replaceMarketplaceLogin,
  requestMarketplaceSync,
  updateMarketplaceAccess,
} from "@/lib/marketplaces/api";
import type {
  Marketplace,
  MarketplaceSource,
  MarketplaceCreate,
  MarketplaceAccessUpdate,
} from "@/lib/marketplaces/types";

const id = "10000000-0000-4000-8000-000000000001";
const skillId = "20000000-0000-4000-8000-000000000002";
const source = {
  provider: "github",
  provider_config: { owner: "acme", repo: "tools", ref: "main", folder: null },
  personal: true,
} satisfies MarketplaceSource;
const marketplace = {
  id,
  name: "Team tools",
  provider: source.provider,
  provider_config: source.provider_config,
  owner_user_id: skillId,
  login_user_id: null,
  public_permission: null,
  installation_policy: "AVAILABLE",
  group_shares: [],
  sync_requested: true,
  sync_pending: true,
  sync_status: null,
  last_synced_revision: null,
  last_synced_at: null,
  last_error: null,
  blocked_entries: {},
  retirement_proposal: null,
  live_skill_count: 0,
  retired_skill_count: 0,
} satisfies Marketplace;

afterEach(() => jest.restoreAllMocks());

test.each(["AVAILABLE", "NOT_AVAILABLE"] as const)(
  "reads %s source settings, counts and retained skills",
  async (installation_policy) => {
    const row = {
      ...marketplace,
      installation_policy,
      group_shares: [
        {
          user_group_id: 7,
          permission: "VIEWER",
          installation_policy,
        },
      ],
      live_skill_count: 2,
      retired_skill_count: 1,
      blocked_entries: { "skills/broken": "Bundle exceeds the file limit" },
    };
    const detail = {
      marketplace: row,
      skills: [
        {
          id: skillId,
          name: "retired-skill",
          current_version_id: null,
          retired_at: "2026-11-08T12:00:00Z",
          follows_marketplace_access: true,
        },
      ],
    };
    // GET list, then GET detail.
    const fetch = jest
      .spyOn(global, "fetch")
      .mockResolvedValueOnce(Response.json([row]))
      .mockResolvedValueOnce(Response.json(detail));
    await expect(listMarketplaces()).resolves.toEqual([row]);
    await expect(getMarketplace(id)).resolves.toEqual(detail);
    expect(fetch).toHaveBeenNthCalledWith(1, "/api/marketplaces");
    expect(fetch).toHaveBeenNthCalledWith(2, `/api/marketplaces/${id}`);
  }
);

test("preserves every preview outcome without treating blocked entries as ready", async () => {
  const preview = {
    status: "complete",
    revision: "commit-a",
    entries: [
      {
        status: "ok",
        entry_key: "a",
        path: "skills/a",
        name: "a",
        description: "A",
      },
      {
        status: "blocked",
        entry_key: "b",
        path: "skills/b",
        reason: "Too large",
      },
      {
        status: "not_supported",
        entry_key: "c",
        reason: "Plugin not supported",
      },
    ],
  };
  // POST preview, once for a valid catalog and once for an invalid catalog.
  const fetch = jest
    .spyOn(global, "fetch")
    .mockResolvedValueOnce(Response.json(preview))
    .mockResolvedValueOnce(
      Response.json({
        status: "failed",
        revision: "b",
        reason: "Missing catalog",
      })
    );
  await expect(previewMarketplace(source)).resolves.toEqual(preview);
  expect(fetch).toHaveBeenCalledWith("/api/marketplaces/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(source),
  });
  await expect(previewMarketplace(source)).resolves.toEqual({
    status: "failed",
    revision: "b",
    reason: "Missing catalog",
  });
});

test("creation and sync keep queued work distinct from an applied revision", async () => {
  // POST create and POST sync both return a queued snapshot.
  const fetch = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(Response.json(marketplace));
  const created = await createMarketplace({ ...source, name: "Team tools" });
  expect(created.sync_requested).toBe(true);
  expect(created.sync_status).toBeNull();
  expect(fetch).toHaveBeenCalledWith(
    "/api/marketplaces",
    expect.objectContaining({
      body: JSON.stringify({ ...source, name: "Team tools" }),
    })
  );
  // A Response body can be consumed only once.
  fetch.mockResolvedValueOnce(Response.json(marketplace));
  await expect(requestMarketplaceSync(id)).resolves.toEqual(marketplace);
  expect(fetch).toHaveBeenLastCalledWith(`/api/marketplaces/${id}/sync`, {
    method: "POST",
  });
});

test("sends the exact retirement pair and never sends the approval flag", async () => {
  const confirmation = { revision: "commit-b", skill_ids: [skillId] };
  const row = {
    ...marketplace,
    sync_status: "needs_confirmation",
    retirement_proposal: { ...confirmation, approved: true },
  };
  // POST exact confirmation.
  const fetch = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(Response.json(row));
  await expect(
    confirmMarketplaceRetirements({ id, confirmation: row.retirement_proposal })
  ).resolves.toEqual(row);
  expect(fetch).toHaveBeenCalledWith(
    `/api/marketplaces/${id}/confirm-retirements`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(confirmation),
    }
  );
});

test("updates defaults, replaces the acting login and removes a source", async () => {
  // PATCH access, POST replace-login, DELETE source.
  const fetch = jest
    .spyOn(global, "fetch")
    .mockResolvedValueOnce(Response.json(marketplace))
    .mockResolvedValueOnce(Response.json(marketplace))
    .mockResolvedValueOnce(Response.json(null));
  const access = {
    public_permission: null,
    group_shares: [
      { group_id: 7, permission: "VIEWER", installation_policy: "REQUIRED" },
    ],
  } as const;
  await updateMarketplaceAccess({
    id,
    access: { ...access, group_shares: [...access.group_shares] },
  });
  expect(fetch).toHaveBeenLastCalledWith(`/api/marketplaces/${id}/access`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(access),
  });
  await replaceMarketplaceLogin(id);
  expect(fetch).toHaveBeenLastCalledWith(
    `/api/marketplaces/${id}/replace-login`,
    { method: "POST" }
  );
  await expect(removeMarketplace(id)).resolves.toBeUndefined();
  expect(fetch).toHaveBeenLastCalledWith(`/api/marketplaces/${id}`, {
    method: "DELETE",
  });
});

test.each([400, 403, 409, 503])(
  "keeps server error details and status %s",
  async (status) => {
    // POST sync error: callers use the existing translated fallback plus fetchErrorDetail.
    jest
      .spyOn(global, "fetch")
      .mockImplementation(async () =>
        Response.json(
          { error_code: "CONFLICT", detail: "Retirement proposal has changed" },
          { status }
        )
      );
    const error = await requestMarketplaceSync(id).catch(
      (caught: unknown) => caught
    );
    expect(error).toBeInstanceOf(FetchError);
    expect(error).toMatchObject({ status });
    expect(fetchErrorDetail(error)).toBe("Retirement proposal has changed");
  }
);

test.each([
  { ...marketplace, sync_requested: "true" },
  { ...marketplace, live_skill_count: -1 },
  { ...marketplace, blocked_entries: { broken: { reason: "invalid shape" } } },
  {
    ...marketplace,
    retirement_proposal: {
      revision: "b",
      skill_ids: ["not-a-uuid"],
      approved: false,
    },
  },
])("rejects malformed management responses", async (row) => {
  // GET list rejects unsafe values instead of coercing them.
  jest.spyOn(global, "fetch").mockResolvedValue(Response.json([row]));
  await expect(listMarketplaces()).rejects.toThrow();
});

test("rejects unknown preview states", async () => {
  // POST preview with a new unsupported entry state.
  jest.spyOn(global, "fetch").mockResolvedValue(
    Response.json({
      status: "complete",
      revision: "a",
      entries: [{ status: "maybe", entry_key: "x" }],
    })
  );
  await expect(previewMarketplace(source)).rejects.toThrow();
});

test("creates a company source with its defaults in one request", async () => {
  const access = {
    public_permission: null,
    installation_policy: "DEFAULT",
    group_shares: [
      { group_id: 7, permission: "VIEWER", installation_policy: "REQUIRED" },
    ],
  } satisfies MarketplaceAccessUpdate;
  const payload = {
    ...source,
    personal: false,
    name: "Company tools",
    access,
  } satisfies MarketplaceCreate;
  const saved = {
    ...marketplace,
    name: payload.name,
    owner_user_id: null,
    installation_policy: access.installation_policy,
    group_shares: [
      {
        user_group_id: 7,
        permission: "VIEWER",
        installation_policy: "REQUIRED",
      },
    ],
  } satisfies Marketplace;
  const fetch = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(Response.json(saved));
  await expect(createMarketplace(payload)).resolves.toEqual(saved);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch).toHaveBeenCalledWith("/api/marketplaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
});
