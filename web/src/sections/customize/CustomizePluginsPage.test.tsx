import { render, screen } from "@tests/setup/test-utils";
import { mockFetch } from "@tests/setup/integrationTestUtils";
import CustomizePluginsPage from "@/sections/customize/CustomizePluginsPage";
import { customFixture } from "@/lib/skills/__fixtures__/picker";

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
