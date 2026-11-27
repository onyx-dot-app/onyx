import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import AddSkillMenu from "@/sections/customize/AddSkillMenu";
import { detailFixture } from "@/sections/marketplaces/__fixtures__/marketplace";

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => window.location.pathname,
  useSearchParams: () => new URLSearchParams(window.location.search),
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

test.each([
  ["/app/customize/plugins", "/app/customize/plugins#marketplaces"],
  ["/admin/plugins", "/admin/plugins#marketplaces"],
])(
  "on %s an added marketplace opens the Marketplaces section and refreshes the plugin list",
  async (path, target) => {
    window.history.replaceState(null, "", path);
    render(<AddSkillMenu upload="plugin" />);
    const user = setupUser();

    await user.click(screen.getByRole("button", { name: "Add" }));
    await user.click(
      await screen.findByRole("menuitem", { name: "Add marketplace" })
    );
    await user.click(screen.getByRole("button", { name: "Finish add" }));

    await waitFor(() =>
      expect(window.location.pathname + window.location.hash).toBe(target)
    );
    await waitFor(() => expect(mockRefreshSkillLists).toHaveBeenCalled());
  }
);

test("an added marketplace scrolls to a Marketplaces section already linked", async () => {
  window.history.replaceState(null, "", "/app/customize/plugins#marketplaces");
  const section = document.createElement("div");
  section.id = "marketplaces";
  section.scrollIntoView = jest.fn();
  document.body.appendChild(section);
  render(<AddSkillMenu upload="plugin" />);
  const user = setupUser();

  await user.click(screen.getByRole("button", { name: "Add" }));
  await user.click(
    await screen.findByRole("menuitem", { name: "Add marketplace" })
  );
  await user.click(screen.getByRole("button", { name: "Finish add" }));

  expect(section.scrollIntoView).toHaveBeenCalled();
  section.remove();
});
