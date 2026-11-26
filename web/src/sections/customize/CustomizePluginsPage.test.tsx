import { PointerEventsCheckLevel } from "@testing-library/user-event";
import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { mockFetch, requestBody } from "@tests/setup/integrationTestUtils";
import CustomizePluginsPage from "@/sections/customize/CustomizePluginsPage";
import { customFixture } from "@/lib/skills/__fixtures__/picker";
import {
  MARKETPLACE_ID,
  detailFixture,
  summaryFixture,
} from "@/sections/marketplaces/__fixtures__/marketplace";

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => window.location.pathname,
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({
    isGlobalHolder: true,
    isScopedManager: false,
  }),
}));
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    user: { id: "user-me", email: "me@example.com" },
    isAdmin: true,
  }),
}));

function plugin(id: string, name: string, over = {}) {
  return customFixture({
    id,
    name,
    kind: "plugin",
    owner: { id: "user-me", email: "me@example.com" },
    ...over,
  });
}

test("an admin's list leaves out the private plugins of other members", async () => {
  window.history.replaceState(null, "", "/app/customize/plugins");
  mockFetch({
    "/api/skills": {
      builtins: [],
      customs: [
        plugin("mine", "my-kit"),
        plugin("theirs", "their-kit", {
          owner: { id: "other", email: "other@example.com" },
          member_visible: false,
        }),
      ],
    },
  });
  render(<CustomizePluginsPage />);

  expect(await screen.findByText("my-kit")).toBeInTheDocument();
  expect(screen.queryByText("their-kit")).not.toBeInTheDocument();
});

test("a plugin that is only a root SKILL.md is left out", async () => {
  window.history.replaceState(null, "", "/app/customize/plugins");
  mockFetch({
    "/api/skills": {
      builtins: [],
      customs: [
        plugin("kit", "my-kit"),
        plugin("lone", "lone-skill", { kind: "skill" }),
      ],
    },
  });
  render(<CustomizePluginsPage />);

  expect(await screen.findByText("my-kit")).toBeInTheDocument();
  expect(screen.queryByText("lone-skill")).not.toBeInTheDocument();
});

test("a plugin that is off because another plugin holds its skill name says so", async () => {
  window.history.replaceState(null, "", "/app/customize/plugins");
  mockFetch({
    "/api/skills": {
      builtins: [],
      customs: [
        plugin("held", "own-kit", {
          enabled: false,
          name_held_by: ["company-kit"],
        }),
      ],
    },
  });
  render(<CustomizePluginsPage />);

  expect(
    await screen.findByText(/Off: company-kit uses the same skill name/)
  ).toBeInTheDocument();
});

test("with no plugins and no marketplaces, one empty state offers upload and add marketplace", async () => {
  window.history.replaceState(null, "", "/app/customize/plugins");
  mockFetch({
    "/api/skills": { builtins: [], customs: [] },
    "/api/marketplaces": { marketplaces: [] },
  });
  render(<CustomizePluginsPage />);

  expect(
    await screen.findByRole("button", { name: "Upload Plugin" })
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Add marketplace" })
  ).toBeInTheDocument();
  expect(screen.getAllByText("No plugins yet")).toHaveLength(1);
  expect(
    screen.queryByRole("table", { name: "Marketplaces" })
  ).not.toBeInTheDocument();
  expect(document.getElementById("marketplaces")).toBeNull();
});

test("the empty state offers add marketplace only once the marketplaces load", async () => {
  window.history.replaceState(null, "", "/app/customize/plugins");
  mockFetch({
    "/api/skills": { builtins: [], customs: [] },
    "/api/marketplaces": () => new Promise<never>(() => undefined),
  });
  render(<CustomizePluginsPage />);

  expect(
    await screen.findByRole("button", { name: "Upload Plugin" })
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Add marketplace" })
  ).not.toBeInTheDocument();
});

test("the Marketplaces section lists marketplaces and Add marketplace opens the add dialog", async () => {
  window.history.replaceState(null, "", "/app/customize/plugins");
  mockFetch({
    "/api/skills": { builtins: [], customs: [] },
    "/api/marketplaces": {
      marketplaces: [summaryFixture({ scope: "company" })],
    },
  });
  render(<CustomizePluginsPage />);

  const table = await screen.findByRole("table", { name: "Marketplaces" });
  expect(within(table).getAllByText("acme/plugins").length).toBeGreaterThan(0);
  expect(table.closest("#marketplaces")).not.toBeNull();
  expect(
    screen.queryByRole("link", { name: "Marketplaces" })
  ).not.toBeInTheDocument();

  await setupUser().click(
    screen.getByRole("button", { name: "Add marketplace" })
  );
  expect(
    await screen.findByRole("dialog", { name: /^Add Marketplace\b/ })
  ).toBeInTheDocument();
});

test("the marketplaces stay usable when the plugins fail to load", async () => {
  window.history.replaceState(null, "", "/app/customize/plugins");
  mockFetch({
    "/api/skills": () => new Response(null, { status: 500 }),
    "/api/marketplaces": { marketplaces: [summaryFixture()] },
  });
  render(<CustomizePluginsPage />);

  expect(
    await screen.findByText("Could not load your plugins.")
  ).toBeInTheDocument();
  expect(
    await screen.findByRole("table", { name: "Marketplaces" })
  ).toBeInTheDocument();
});

test("the marketplaces show while the plugins still load", async () => {
  window.history.replaceState(null, "", "/app/customize/plugins");
  mockFetch({
    "/api/skills": () => new Promise<never>(() => undefined),
    "/api/marketplaces": { marketplaces: [summaryFixture()] },
  });
  render(<CustomizePluginsPage />);

  expect(
    await screen.findByRole("table", { name: "Marketplaces" })
  ).toBeInTheDocument();
});

test("a link to #marketplaces scrolls to the section once it loads", async () => {
  window.history.replaceState(null, "", "/app/customize/plugins#marketplaces");
  const scrollIntoView = jest.fn();
  Element.prototype.scrollIntoView = scrollIntoView;
  mockFetch({
    "/api/skills": { builtins: [], customs: [] },
    "/api/marketplaces": { marketplaces: [summaryFixture()] },
  });
  render(<CustomizePluginsPage />);

  await screen.findByRole("table", { name: "Marketplaces" });
  expect(scrollIntoView).toHaveBeenCalledTimes(1);
  expect(scrollIntoView.mock.contexts[0]).toBe(
    document.getElementById("marketplaces")
  );
});

test("a sync that changes a marketplace refreshes the plugins once", async () => {
  window.history.replaceState(null, "", "/app/customize/plugins");
  let synced = false;
  const fetchMock = mockFetch({
    "/api/skills": { builtins: [], customs: [] },
    "/api/marketplaces": () => ({
      marketplaces: [summaryFixture({ plugin_count: synced ? 3 : 2 })],
    }),
    [`POST /api/marketplaces/${MARKETPLACE_ID}/sync`]: () => {
      synced = true;
      return detailFixture();
    },
  });
  const skillFetches = () =>
    fetchMock.mock.calls.filter(([url]) => url === "/api/skills").length;
  render(<CustomizePluginsPage />);

  await screen.findByRole("table", { name: "Marketplaces" });
  const before = skillFetches();
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  await user.click(
    screen.getByRole("button", { name: "Actions for acme/plugins" })
  );
  await user.click(await screen.findByRole("menuitem", { name: /Sync now/ }));
  await screen.findByText("3 plugins");
  // Every subscriber refreshes in the same effect pass, so the first refetch
  // means all of them ran.
  await waitFor(() => expect(skillFetches()).toBeGreaterThan(before));
  expect(skillFetches()).toBe(before + 1);
});

test("two copies of a plugin say which marketplace each comes from", async () => {
  window.history.replaceState(null, "", "/app/customize/plugins");
  const marketplace = {
    name: "anthropic-agent-skills",
    kind: "github" as const,
    repository: "anthropics/skills",
  };
  mockFetch({
    "/api/skills": {
      builtins: [],
      customs: [
        plugin("company", "academy-guide", {
          owner: null,
          marketplace: { ...marketplace, id: "m-company", personal: false },
        }),
        plugin("personal", "academy-guide", {
          marketplace: { ...marketplace, id: "m-personal", personal: true },
        }),
      ],
    },
  });
  render(<CustomizePluginsPage />);

  expect(
    await screen.findByText(/^from anthropic-agent-skills \(company\)/)
  ).toBeInTheDocument();
  expect(
    screen.getByText(/^from anthropic-agent-skills \(personal\)/)
  ).toBeInTheDocument();
});

describe("admin page", () => {
  test("lists every plugin, leaves skills out and opens plugins in the admin panel", async () => {
    window.history.replaceState(null, "", "/admin/plugins");
    mockFetch({
      "/api/skills": {
        builtins: [],
        customs: [
          plugin("11111111-1111-4111-8111-111111111111", "my-kit"),
          plugin("theirs", "their-kit", {
            owner: { id: "other", email: "other@example.com" },
            member_visible: false,
          }),
          plugin("lone", "lone-skill", { kind: "skill" }),
        ],
      },
      "/api/marketplaces": { marketplaces: [summaryFixture()] },
    });
    render(<CustomizePluginsPage />);

    expect(await screen.findByText("my-kit")).toBeInTheDocument();
    expect(screen.getByText("their-kit")).toBeInTheDocument();
    expect(screen.queryByText("lone-skill")).not.toBeInTheDocument();
    expect(
      await screen.findByRole("table", { name: "Marketplaces" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Add marketplace" })
    ).toBeInTheDocument();

    await setupUser().click(screen.getByRole("row", { name: "Open my-kit" }));
    await waitFor(() =>
      expect(window.location.pathname).toBe(
        "/admin/plugins/11111111-1111-4111-8111-111111111111"
      )
    );
  });

  test("an unpublished upload with no owner says so, not by you", async () => {
    window.history.replaceState(null, "", "/admin/plugins");
    mockFetch({
      "/api/skills": {
        builtins: [],
        customs: [
          plugin("mine", "my-kit"),
          plugin("orphan", "orphan-kit", { owner: null }),
        ],
      },
      "/api/marketplaces": { marketplaces: [] },
    });
    render(<CustomizePluginsPage />);

    const orphan = await screen.findByRole("row", { name: "Open orphan-kit" });
    expect(within(orphan).getByText("No owner")).toBeInTheDocument();
    expect(within(orphan).queryByText("by you")).not.toBeInTheDocument();
    expect(
      within(screen.getByRole("row", { name: "Open my-kit" })).getByText(
        "by you"
      )
    ).toBeInTheDocument();
  });

  test("deletes the selected plugins in one bulk request after the confirm", async () => {
    window.history.replaceState(null, "", "/admin/plugins");
    const fetchMock = mockFetch({
      "/api/skills": {
        builtins: [],
        customs: [
          plugin("a", "alpha-kit", { user_permission: "OWNER" }),
          plugin("b", "beta-kit", { user_permission: "EDITOR" }),
          plugin("c", "gamma-kit", { user_permission: "OWNER" }),
        ],
      },
      "/api/marketplaces": { marketplaces: [] },
      "POST /api/skills/bulk": { succeeded: ["a", "b"], failed: [] },
    });
    render(<CustomizePluginsPage />);
    const user = setupUser({
      pointerEventsCheck: PointerEventsCheckLevel.Never,
    });

    await user.click(
      await screen.findByRole("checkbox", { name: "Select alpha-kit" })
    );
    await user.click(screen.getByRole("checkbox", { name: "Select beta-kit" }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(await screen.findByRole("menuitem", { name: /Delete/ }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Delete 2 plugins?")).toBeVisible();
    const list = within(dialog).getByRole("list");
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(requestBody(fetchMock, "POST", "/api/skills/bulk")).toEqual({
        action: "delete",
        skill_ids: ["a", "b"],
      })
    );
    await waitFor(() =>
      expect(screen.queryByText("2 selected")).not.toBeInTheDocument()
    );
  });

  test("a plugin the admin cannot manage cannot be selected", async () => {
    window.history.replaceState(null, "", "/admin/plugins");
    mockFetch({
      "/api/skills": {
        builtins: [],
        customs: [
          plugin("mine", "my-kit", { user_permission: "OWNER" }),
          plugin("viewed", "viewed-kit", { user_permission: "VIEWER" }),
        ],
      },
      "/api/marketplaces": { marketplaces: [] },
    });
    render(<CustomizePluginsPage />);

    expect(
      await screen.findByRole("checkbox", { name: "Select viewed-kit" })
    ).toHaveAttribute("aria-disabled", "true");
    await setupUser().click(
      screen.getByRole("checkbox", { name: "Select all" })
    );
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "Select my-kit" })
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Select viewed-kit" })
    ).not.toBeChecked();
  });

  test("bulk Share skips a personal marketplace's plugin and publishing a synced one", async () => {
    window.history.replaceState(null, "", "/admin/plugins");
    const marketplace = {
      name: "anthropic-agent-skills",
      kind: "github" as const,
      repository: "anthropics/skills",
    };
    mockFetch({
      "/api/skills": {
        builtins: [],
        customs: [
          plugin("personal", "personal-kit", {
            user_permission: "OWNER",
            content_locked: true,
            marketplace: { ...marketplace, id: "m-personal", personal: true },
          }),
          plugin("company", "company-kit", {
            user_permission: "OWNER",
            content_locked: true,
            marketplace: { ...marketplace, id: "m-company", personal: false },
          }),
        ],
      },
      "/api/marketplaces": { marketplaces: [] },
    });
    render(<CustomizePluginsPage />);
    const user = setupUser({
      pointerEventsCheck: PointerEventsCheckLevel.Never,
    });

    await user.click(
      await screen.findByRole("checkbox", { name: "Select personal-kit" })
    );
    expect(screen.getByRole("button", { name: "Share" })).toBeDisabled();

    await user.click(
      screen.getByRole("checkbox", { name: "Select personal-kit" })
    );
    await user.click(
      screen.getByRole("checkbox", { name: "Select company-kit" })
    );
    await user.click(screen.getByRole("button", { name: "Share" }));
    expect(
      await screen.findByRole("button", { name: "Who can access" })
    ).toBeDisabled();
  });
});
