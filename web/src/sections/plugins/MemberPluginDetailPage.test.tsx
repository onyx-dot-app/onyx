import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import type { PluginNeed } from "@/lib/plugins/types";
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

test("an uploaded plugin lists its needs and turning it on shows the ones not on", async () => {
  window.history.replaceState(null, "", `/app/customize/plugins/${PLUGIN_ID}`);
  const needs: PluginNeed[] = [
    {
      kind: "mcp",
      name: "linear",
      url: "https://mcp.linear.app/mcp",
      transport: "http",
      supported: true,
      state: "not_added",
      integration_id: null,
    },
    {
      kind: "mcp",
      name: "git",
      url: null,
      transport: "stdio",
      supported: false,
      state: "not_supported",
      integration_id: null,
    },
  ];
  const plugin = customFixture({
    id: PLUGIN_ID,
    name: "review-kit",
    enabled: false,
    kind: "plugin",
    needed_count: 1,
    plugin: {
      manifest: null,
      skills: [
        { path: "skills/review", name: "review", description: "Review." },
        { path: "skills/plan", name: "plan", description: "Plan." },
      ],
      needs,
    },
  });
  mockFetch({
    "/api/skills": { builtins: [], customs: [{ ...plugin, plugin: null }] },
    [`/api/skills/${PLUGIN_ID}`]: plugin,
    "/api/integrations": [],
    [`PUT /api/skills/${PLUGIN_ID}/enabled`]: { ...plugin, enabled: true },
  });
  const user = setupUser();
  render(<MemberPluginDetailPage pluginId={PLUGIN_ID} />);

  expect(
    await screen.findByRole("tab", { name: "Integrations · 2" })
  ).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Skills · 2" })).toBeInTheDocument();

  await user.click(screen.getByRole("switch", { name: "Use review-kit" }));
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText("review-kit is on")).toBeInTheDocument();
  expect(within(dialog).getByText("Not added")).toBeInTheDocument();
  expect(within(dialog).getByText("Not supported in Onyx")).toBeInTheDocument();
});
