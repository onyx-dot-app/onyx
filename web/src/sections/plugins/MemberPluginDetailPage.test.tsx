import { render, screen, waitFor } from "@tests/setup/test-utils";
import MemberPluginDetailPage from "@/sections/plugins/MemberPluginDetailPage";
import { customFixture } from "@/lib/skills/__fixtures__/picker";
import { mockFetch } from "@tests/setup/integrationTestUtils";

const PLUGIN_ID = "11111111-1111-4111-8111-111111111111";

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => window.location.pathname,
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({
    isGlobalHolder: false,
    isScopedManager: false,
  }),
}));
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: { email: "me@example.com" } }),
}));

afterEach(() => jest.restoreAllMocks());

test("a plugin that is one skill opens the skill page", async () => {
  window.history.replaceState(null, "", `/app/customize/plugins/${PLUGIN_ID}`);
  mockFetch({
    "/api/skills": {
      builtins: [],
      customs: [
        customFixture({
          id: PLUGIN_ID,
          name: "report-writer",
          user_permission: "OWNER",
        }),
      ],
    },
  });
  render(<MemberPluginDetailPage pluginId={PLUGIN_ID} />);
  await waitFor(() =>
    expect(window.location.pathname).toBe(`/app/customize/skills/${PLUGIN_ID}`)
  );
  expect(
    screen.queryByRole("tab", { name: /^Skills/ })
  ).not.toBeInTheDocument();
});
