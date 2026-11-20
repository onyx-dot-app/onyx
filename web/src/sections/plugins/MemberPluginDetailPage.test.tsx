import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import type { MemberIntegration } from "@/lib/integrations/types";
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
      url_problem: null,
      supported: true,
      state: "not_added",
      integration_id: null,
    },
    {
      kind: "mcp",
      name: "git",
      url: null,
      transport: "stdio",
      url_problem: null,
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
    await screen.findByRole("tab", { name: "Integrations · 1" })
  ).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Skills · 2" })).toBeInTheDocument();

  await user.click(screen.getByRole("switch", { name: "Use review-kit" }));
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText("review-kit is on")).toBeInTheDocument();
  expect(within(dialog).getByText("Not added")).toBeInTheDocument();
  expect(within(dialog).getByText("Not supported in Onyx")).toBeInTheDocument();
});

test("turning on a plugin whose skill name is taken asks to switch", async () => {
  window.history.replaceState(null, "", `/app/customize/plugins/${PLUGIN_ID}`);
  const plugin = customFixture({
    id: PLUGIN_ID,
    name: "review-kit",
    enabled: false,
    kind: "plugin",
    plugin: {
      manifest: null,
      skills: [
        { path: "skills/review", name: "review", description: "Review." },
      ],
      needs: [],
    },
  });
  const fetchMock = mockFetch({
    "/api/skills": { builtins: [], customs: [{ ...plugin, plugin: null }] },
    [`/api/skills/${PLUGIN_ID}`]: plugin,
    [`PUT /api/skills/${PLUGIN_ID}/enabled`]: (init?: RequestInit) =>
      typeof init?.body === "string" && JSON.parse(init.body).replace_conflict
        ? { ...plugin, enabled: true }
        : new Response(
            JSON.stringify({
              error_code: "SKILL_NAME_CONFLICT",
              detail: "Another skill is named review.",
              conflict_names: ["other-kit"],
            }),
            { status: 409 }
          ),
  });
  const user = setupUser();
  render(<MemberPluginDetailPage pluginId={PLUGIN_ID} />);

  await user.click(
    await screen.findByRole("switch", { name: "Use review-kit" })
  );
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText("Turn on “review-kit”?")).toBeInTheDocument();
  expect(
    within(dialog).getByText("Turning on “review-kit” turns off “other-kit”.")
  ).toBeInTheDocument();

  await user.click(within(dialog).getByRole("button", { name: "Switch" }));
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.filter(
        ([, init]) =>
          typeof init?.body === "string" &&
          JSON.parse(init.body).replace_conflict === true
      )
    ).toHaveLength(1)
  );
});

test("turning on a plugin refreshes the integration rows it turned on", async () => {
  window.history.replaceState(
    null,
    "",
    `/app/customize/plugins/${PLUGIN_ID}?tab=integrations`
  );
  const searchNeed = (state: PluginNeed["state"]): PluginNeed => ({
    kind: "mcp",
    name: "search",
    url: "https://example.com/search",
    transport: "http",
    url_problem: null,
    supported: true,
    state,
    integration_id: 3,
  });
  const plugin = customFixture({
    id: PLUGIN_ID,
    name: "review-kit",
    enabled: false,
    kind: "plugin",
    plugin: {
      manifest: null,
      skills: [
        { path: "skills/review", name: "review", description: "Review." },
      ],
      needs: [searchNeed("turn_on")],
    },
  });
  let enabled = false;
  const integration = (): MemberIntegration => ({
    id: 3,
    kind: "mcp",
    shape: "mcp_server",
    name: "Search",
    description: null,
    preset_id: null,
    auth_mode: "none",
    auth_method: null,
    credential_fields: [],
    status: { state: "connected", reason: null },
    access: {
      state: enabled ? "on" : "turn_on",
      installation_policy: "AVAILABLE",
      user_choice: null,
      user_enabled: enabled,
      owner_email: null,
      is_owner: false,
      can_manage: false,
      shared_with_everyone: true,
    },
    users_can_save_always_allow: false,
    credential_values: {},
    external_app_id: null,
    service_urls: [],
    mcp_server_id: null,
    server_url: null,
  });
  mockFetch({
    "/api/skills": { builtins: [], customs: [{ ...plugin, plugin: null }] },
    [`/api/skills/${PLUGIN_ID}`]: plugin,
    "/api/integrations": () => [integration()],
    [`PUT /api/skills/${PLUGIN_ID}/enabled`]: () => {
      enabled = true;
      return {
        ...plugin,
        enabled: true,
        plugin: { ...plugin.plugin, needs: [searchNeed("on")] },
      };
    },
  });
  const user = setupUser();
  render(<MemberPluginDetailPage pluginId={PLUGIN_ID} />);

  const row = await screen.findByLabelText("search");
  expect(await within(row).findByText("Turn on")).toBeInTheDocument();
  await user.click(screen.getByRole("switch", { name: "Use review-kit" }));

  await waitFor(() => expect(within(row).getByText("On")).toBeInTheDocument());
});

test("the owner shares, uploads a new version and deletes the plugin from its page", async () => {
  window.history.replaceState(null, "", `/app/customize/plugins/${PLUGIN_ID}`);
  const plugin = customFixture({
    id: PLUGIN_ID,
    name: "review-kit",
    kind: "plugin",
    user_permission: "OWNER",
    can_delete: true,
    enabled: false,
    name_held_by: ["company-kit"],
    plugin: {
      manifest: null,
      skills: [
        { path: "skills/review", name: "review", description: "Review." },
      ],
      needs: [],
    },
  });
  const fetchMock = mockFetch({
    "/api/skills": { builtins: [], customs: [{ ...plugin, plugin: null }] },
    [`/api/skills/${PLUGIN_ID}`]: plugin,
    [`DELETE /api/skills/custom/${PLUGIN_ID}`]: new Response(null, {
      status: 204,
    }),
  });
  const user = setupUser();
  render(<MemberPluginDetailPage pluginId={PLUGIN_ID} />);

  expect(
    await screen.findByText(
      "Off because company-kit uses the same skill name. Turn this plugin on to use it instead."
    )
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Share" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "More actions" }));
  expect(
    await screen.findByRole("menuitem", { name: "Upload New Version" })
  ).toBeInTheDocument();
  await user.click(screen.getByRole("menuitem", { name: "Delete Plugin" }));
  const dialog = await screen.findByRole("dialog");
  await user.click(within(dialog).getByRole("button", { name: "Delete" }));

  await waitFor(() =>
    expect(window.location.pathname).toBe("/app/customize/plugins")
  );
  expect(
    fetchMock.mock.calls.some(
      ([url, init]) =>
        String(url).endsWith(`/api/skills/custom/${PLUGIN_ID}`) &&
        init?.method === "DELETE"
    )
  ).toBe(true);
});

test("the Skills tab opens the instructions of one skill", async () => {
  window.history.replaceState(
    null,
    "",
    `/app/customize/plugins/${PLUGIN_ID}?tab=skills`
  );
  const plugin = customFixture({
    id: PLUGIN_ID,
    name: "review-kit",
    kind: "plugin",
    plugin: {
      manifest: null,
      skills: [
        { path: "skills/review", name: "review", description: "Review." },
        { path: "skills/plan", name: "plan", description: "Plan." },
      ],
      needs: [],
    },
  });
  mockFetch({
    "/api/skills": { builtins: [], customs: [{ ...plugin, plugin: null }] },
    [`/api/skills/${PLUGIN_ID}`]: plugin,
    [`/api/skills/${PLUGIN_ID}/plugin-skill?path=skills%2Fplan`]: {
      instructions_markdown: "Write the plan first.",
    },
  });
  const user = setupUser();
  render(<MemberPluginDetailPage pluginId={PLUGIN_ID} />);

  await user.click(
    await screen.findByRole("button", { name: "Read the plan skill" })
  );

  expect(await screen.findByText("Write the plan first.")).toBeInTheDocument();
});

test("a synced plugin names its repository and hides restore and publish", async () => {
  window.history.replaceState(
    null,
    "",
    `/app/customize/plugins/${PLUGIN_ID}?tab=versions`
  );
  const plugin = customFixture({
    id: PLUGIN_ID,
    name: "review-kit",
    kind: "plugin",
    user_permission: "OWNER",
    current_version_id: "version-2",
    current_version_number: 2,
    published_version_number: 1,
    content_locked: true,
    marketplace: {
      id: "22222222-2222-4222-8222-222222222222",
      name: "acme/plugins",
      kind: "github",
      repository: "acme/plugins",
      personal: true,
    },
    plugin: { manifest: null, skills: [], needs: [] },
  });
  mockFetch({
    "/api/skills": { builtins: [], customs: [plugin] },
    [`/api/skills/${PLUGIN_ID}`]: plugin,
    [`/api/skills/custom/${PLUGIN_ID}/versions`]: [
      {
        id: "version-2",
        version_number: 2,
        created_at: "2026-11-02T10:00:00Z",
        created_by_email: "me@example.com",
        is_current: true,
        review_status: "draft",
      },
      {
        id: "version-1",
        version_number: 1,
        created_at: "2026-11-01T10:00:00Z",
        created_by_email: "me@example.com",
        is_current: false,
        review_status: "published",
      },
    ],
  });
  render(<MemberPluginDetailPage pluginId={PLUGIN_ID} />);

  expect(
    await screen.findByText("Synced from acme/plugins")
  ).toBeInTheDocument();
  expect(
    await screen.findByText(
      "This plugin syncs from GitHub, so you change it in GitHub."
    )
  ).toBeInTheDocument();
  expect(await screen.findByText("Version 1")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Restore version 1" })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Publish update" })
  ).not.toBeInTheDocument();
});

test("a synced plugin names its marketplace and says that GitHub holds it", async () => {
  window.history.replaceState(null, "", `/app/customize/plugins/${PLUGIN_ID}`);
  const plugin = customFixture({
    id: PLUGIN_ID,
    name: "review-kit",
    kind: "plugin",
    user_permission: "OWNER",
    owner: { id: "me", email: "me@example.com" },
    content_locked: true,
    marketplace: {
      id: "22222222-2222-4222-8222-222222222222",
      name: "acme-tools",
      kind: "github",
      repository: "acme/plugins",
      personal: true,
    },
    plugin: { manifest: null, skills: [], needs: [] },
  });
  mockFetch({
    "/api/skills": { builtins: [], customs: [plugin] },
    [`/api/skills/${PLUGIN_ID}`]: plugin,
  });
  render(<MemberPluginDetailPage pluginId={PLUGIN_ID} />);

  expect(
    await screen.findByText("Managed by the acme-tools marketplace")
  ).toBeInTheDocument();
  expect(
    screen.getByText("acme-tools marketplace, personal (acme/plugins)")
  ).toBeInTheDocument();
  expect(screen.queryByText("My uploads")).not.toBeInTheDocument();
});

test("a personal synced plugin offers neither Share nor Upload New Version", async () => {
  window.history.replaceState(null, "", `/app/customize/plugins/${PLUGIN_ID}`);
  const plugin = customFixture({
    id: PLUGIN_ID,
    name: "review-kit",
    kind: "plugin",
    user_permission: "OWNER",
    can_delete: false,
    content_locked: true,
    marketplace: {
      id: "22222222-2222-4222-8222-222222222222",
      name: "acme-tools",
      kind: "github",
      repository: "acme/plugins",
      personal: true,
    },
    plugin: { manifest: null, skills: [], needs: [] },
  });
  mockFetch({
    "/api/skills": { builtins: [], customs: [{ ...plugin, plugin: null }] },
    [`/api/skills/${PLUGIN_ID}`]: plugin,
  });
  render(<MemberPluginDetailPage pluginId={PLUGIN_ID} />);

  expect(
    await screen.findByText("Managed by the acme-tools marketplace")
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Share" })).toBeNull();
  expect(screen.queryByRole("button", { name: "More actions" })).toBeNull();
});
