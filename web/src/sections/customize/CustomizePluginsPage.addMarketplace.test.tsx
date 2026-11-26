import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { mockFetch } from "@tests/setup/integrationTestUtils";
import CustomizePluginsPage from "@/sections/customize/CustomizePluginsPage";
import { detailFixture } from "@/sections/marketplaces/__fixtures__/marketplace";

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation",
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
const mockRefreshSkillLists = jest.fn(() => Promise.resolve(true));
jest.mock("@/lib/skills/cache", () => ({
  ...jest.requireActual("@/lib/skills/cache"),
  refreshSkillListsChecked: () => mockRefreshSkillLists(),
}));
jest.mock("@/sections/marketplaces/AddMarketplaceModal", () => ({
  __esModule: true,
  default: ({
    open,
    onAdded,
  }: {
    open: boolean;
    onAdded: (marketplace: ReturnType<typeof detailFixture>) => void;
  }) =>
    open ? (
      <button onClick={() => onAdded(detailFixture())}>Finish add</button>
    ) : null,
}));

beforeEach(() => {
  mockRefreshSkillLists.mockClear();
  mockFetch({
    "/api/skills": { builtins: [], customs: [] },
    "/api/marketplaces": { marketplaces: [] },
  });
});

async function addFromMenu(): Promise<void> {
  const user = setupUser();
  await user.click(await screen.findByRole("button", { name: "Add" }));
  await user.click(
    await screen.findByRole("menuitem", { name: "Add marketplace" }),
  );
  await user.click(screen.getByRole("button", { name: "Finish add" }));
}

async function addFromEmptyState(): Promise<void> {
  const user = setupUser();
  await user.click(
    await screen.findByRole("button", { name: "Add marketplace" }),
  );
  await user.click(screen.getByRole("button", { name: "Finish add" }));
}

test.each([
  ["/app/customize/plugins", "/app/customize/plugins#marketplaces"],
  ["/admin/plugins", "/admin/plugins#marketplaces"],
])(
  "on %s an added marketplace opens the Marketplaces section and refreshes the plugin list",
  async (path, target) => {
    window.history.replaceState(null, "", path);
    render(<CustomizePluginsPage />);

    await addFromMenu();

    await waitFor(() =>
      expect(window.location.pathname + window.location.hash).toBe(target),
    );
    await waitFor(() => expect(mockRefreshSkillLists).toHaveBeenCalled());
  },
);

test("a marketplace added from the empty state refreshes the plugin list", async () => {
  window.history.replaceState(null, "", "/app/customize/plugins");
  render(<CustomizePluginsPage />);

  await addFromEmptyState();

  await waitFor(() => expect(mockRefreshSkillLists).toHaveBeenCalled());
});

test("an added marketplace scrolls to a Marketplaces section already linked", async () => {
  window.history.replaceState(null, "", "/app/customize/plugins#marketplaces");
  const section = document.createElement("div");
  section.id = "marketplaces";
  section.scrollIntoView = jest.fn();
  document.body.appendChild(section);
  render(<CustomizePluginsPage />);

  await addFromMenu();

  expect(section.scrollIntoView).toHaveBeenCalled();
  section.remove();
});
