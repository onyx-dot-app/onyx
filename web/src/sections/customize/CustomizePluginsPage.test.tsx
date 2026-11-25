import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { mockFetch } from "@tests/setup/integrationTestUtils";
import CustomizePluginsPage from "@/sections/customize/CustomizePluginsPage";
import { customFixture } from "@/lib/skills/__fixtures__/picker";
import { summaryFixture } from "@/sections/marketplaces/__fixtures__/marketplace";

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

test("the empty list offers to upload a plugin", async () => {
  window.history.replaceState(null, "", "/app/customize/plugins");
  mockFetch({ "/api/skills": { builtins: [], customs: [] } });
  render(<CustomizePluginsPage />);

  expect(
    await screen.findByRole("button", { name: "Upload Plugin" })
  ).toBeInTheDocument();
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

    await setupUser().click(
      screen.getByRole("button", { name: "Open my-kit" })
    );
    await waitFor(() =>
      expect(window.location.pathname).toBe(
        "/admin/plugins/11111111-1111-4111-8111-111111111111"
      )
    );
  });
});
