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
  "on %s an added marketplace opens the Marketplaces section",
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
  }
);
