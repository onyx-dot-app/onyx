import { PointerEventsCheckLevel } from "@testing-library/user-event";
import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { toast } from "@opal/layouts";
import MemberPluginDetailPage from "@/sections/plugins/MemberPluginDetailPage";
import messages from "@/i18n/messages/en.json";
import { customFixture } from "@/lib/skills/__fixtures__/picker";
import { mockFetch, requestBody } from "@tests/setup/integrationTestUtils";
import {
  LINEAR_PLUGIN_ID,
  makeMemberAction,
  makeMemberIntegration,
} from "@tests/setup/memberIntegrationTestUtils";
import type {
  MemberIntegration,
  PluginAccessView,
} from "@/lib/integrations/types";

const copy = messages.plugins.member;
const mockLoadPage = jest.fn();
let mockGlobalHolder = false;

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => window.location.pathname,
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
jest.mock("@opal/navigation", () => ({
  ...jest.requireActual<typeof import("@opal/navigation")>("@opal/navigation"),
  loadPage: (url: string) => mockLoadPage(url),
}));
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({
    isGlobalHolder: mockGlobalHolder,
    isScopedManager: false,
  }),
}));
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: { email: "me@example.com" } }),
}));

const RETURN_PATH = `/app/plugins/${LINEAR_PLUGIN_ID}?tab=integrations`;
const AUTHORIZATION_URL = "https://linear.app/oauth/authorize?state=attempt-1";

function user() {
  return setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
}

function open(integrations: MemberIntegration[], extra = {}) {
  window.history.replaceState(null, "", RETURN_PATH);
  const fetchMock = mockFetch({
    "/api/skills": { builtins: [], customs: [] },
    "/api/integrations": integrations,
    ...extra,
  });
  render(<MemberPluginDetailPage pluginId={LINEAR_PLUGIN_ID} />);
  return fetchMock;
}

function status(
  state: MemberIntegration["status"]["state"],
  reason: string | null = null
): MemberIntegration["status"] {
  return { state, reason };
}

afterEach(() => {
  jest.restoreAllMocks();
  mockLoadPage.mockClear();
  mockGlobalHolder = false;
});

test("shows only the tabs with content", async () => {
  open([makeMemberIntegration()]);
  expect(
    await screen.findByRole("tab", { name: copy.detail.tabs.integrations })
  ).toHaveAttribute("aria-selected", "true");
  expect(
    screen.getByRole("tab", { name: copy.detail.tabs.overview })
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("tab", { name: copy.detail.tabs.skills })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("tab", { name: copy.detail.tabs.versions })
  ).not.toBeInTheDocument();
});

test("a skill plugin shows its skills and versions", async () => {
  window.history.replaceState(null, "", `/app/plugins/${LINEAR_PLUGIN_ID}`);
  mockFetch({
    "/api/skills": {
      builtins: [],
      customs: [
        customFixture({
          id: LINEAR_PLUGIN_ID,
          name: "report-writer",
          user_permission: "OWNER",
        }),
      ],
    },
    "/api/integrations": [],
  });
  render(<MemberPluginDetailPage pluginId={LINEAR_PLUGIN_ID} />);
  expect(
    await screen.findByRole("tab", { name: copy.detail.tabs.skills })
  ).toBeInTheDocument();
  expect(
    screen.getByRole("tab", { name: copy.detail.tabs.versions })
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("tab", { name: copy.detail.tabs.integrations })
  ).not.toBeInTheDocument();
});

test("shows each of the four statuses with its action", async () => {
  open([
    makeMemberIntegration({
      id: 1,
      name: "Connected app",
      status: status("connected"),
    }),
    makeMemberIntegration({ id: 2, name: "New app" }),
    makeMemberIntegration({
      id: 3,
      name: "Old app",
      status: status(
        "needs_reconnect",
        "Your admin changed the sign-in settings"
      ),
    }),
    makeMemberIntegration({
      id: 4,
      name: "Shared app",
      auth_mode: "shared",
      status: status("not_set_up"),
    }),
    makeMemberIntegration({
      id: 5,
      name: "Stale shared app",
      auth_mode: "shared",
      status: status("needs_reconnect", "The organization account expired"),
    }),
  ]);
  expect(await screen.findByText("Connected")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Disconnect Connected app" })
  ).toBeVisible();
  expect(screen.getByText("Not connected")).toBeVisible();
  expect(screen.getByRole("button", { name: "Connect New app" })).toBeVisible();
  expect(
    screen.getByText("Your admin changed the sign-in settings")
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Reconnect Old app" })
  ).toBeVisible();
  expect(screen.getAllByText(copy.connection.askAdmin)).toHaveLength(2);
  expect(
    screen.queryByRole("button", { name: /Shared app/ })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /Stale shared app/ })
  ).not.toBeInTheDocument();
});

test("Disconnect is a new button after the API key form connects", async () => {
  const integration = makeMemberIntegration({
    id: 2,
    name: "Reports API",
    auth_method: "api_key",
    credential_fields: [{ key: "token", label: "API Token", secret: true }],
  });
  let state: MemberIntegration["status"]["state"] = "not_connected";
  open([], {
    "/api/integrations": () => [{ ...integration, status: status(state) }],
    "PUT /api/integrations/2/connection": () => {
      state = "connected";
      return status(state);
    },
    "/api/action-policies/integration/2": {
      users_can_save_always_allow: false,
      actions: [],
    },
  });
  const u = user();
  const connect = await screen.findByRole("button", {
    name: "Connect Reports API",
  });
  await u.click(connect);
  const dialog = await screen.findByRole("dialog");
  await u.type(within(dialog).getByLabelText("API Token"), "secret-1");
  await u.click(
    within(dialog).getByRole("button", { name: copy.credentials.submit.label })
  );
  // A reused button animates its label and ignores clicks until it shows
  // the new label.
  expect(
    await screen.findByRole("button", { name: "Disconnect Reports API" })
  ).not.toBe(connect);
});

test("OAuth continues in this tab when the browser blocks the new tab", async () => {
  jest.spyOn(window, "open").mockReturnValue(null);
  open([makeMemberIntegration()], {
    "POST /api/integrations/1/oauth/start": {
      authorization_url: AUTHORIZATION_URL,
    },
  });
  await user().click(
    await screen.findByRole("button", { name: "Connect Linear" })
  );
  await waitFor(() =>
    expect(mockLoadPage).toHaveBeenCalledWith(AUTHORIZATION_URL)
  );
});

test("an action that asks offers Always allow", async () => {
  const policies = {
    users_can_save_always_allow: true,
    actions: [
      makeMemberAction(),
      makeMemberAction({
        key: "list_issues",
        display_name: "List issues",
        read_only: true,
        effective_admin_policy: "allow",
      }),
    ],
  };
  const fetchMock = open(
    [
      makeMemberIntegration({
        status: status("connected"),
        users_can_save_always_allow: true,
      }),
    ],
    {
      "/api/action-policies/integration/1": policies,
      "PUT /api/action-policies/integration/1": {
        ...policies,
        actions: [
          { ...policies.actions[0], user_policy: "allow" },
          policies.actions[1],
        ],
      },
    }
  );
  const toggle = await screen.findByRole("switch", {
    name: "Always allow Create issue",
  });
  expect(screen.getByText("Allow")).toBeVisible();
  expect(
    screen.queryByRole("switch", { name: "Always allow List issues" })
  ).not.toBeInTheDocument();
  await user().click(toggle);
  await waitFor(() =>
    expect(
      requestBody(fetchMock, "PUT", "/api/action-policies/integration/1")
    ).toEqual({ actions: { create_issue: "allow" } })
  );
  await waitFor(() => expect(toggle).toBeChecked());
});

test("an action that always asks shows a locked Always allow with the reason", async () => {
  open(
    [
      makeMemberIntegration({
        status: status("connected"),
        users_can_save_always_allow: true,
      }),
    ],
    {
      "/api/action-policies/integration/1": {
        users_can_save_always_allow: true,
        actions: [
          makeMemberAction({
            key: "unspecified",
            display_name: "Any request",
            always_asks: true,
          }),
        ],
      },
    }
  );
  expect(
    await screen.findByRole("switch", { name: "Always allow Any request" })
  ).toHaveAttribute("aria-disabled", "true");
  expect(
    screen.getByText("Craft asks for approval for each of these requests.")
  ).toBeVisible();
});

function withPlugin(
  plugin: Partial<MemberIntegration["plugins"][number]>
): MemberIntegration {
  const base = makeMemberIntegration();
  const ref = base.plugins[0];
  if (!ref) throw new Error("No plugin ref");
  return { ...base, plugins: [{ ...ref, ...plugin }] };
}

function overview(integrations: MemberIntegration[], extra = {}) {
  const fetchMock = open(integrations, extra);
  window.history.replaceState(null, "", `/app/plugins/${LINEAR_PLUGIN_ID}`);
  return fetchMock;
}

test("the member turns an integration plugin on", async () => {
  const fetchMock = overview([withPlugin({ enabled: false })], {
    [`PUT /api/plugins/${LINEAR_PLUGIN_ID}/enabled`]: {
      plugin_id: LINEAR_PLUGIN_ID,
      enabled: true,
      installation_policy: "AVAILABLE",
    },
  });
  const u = user();
  const toggle = await screen.findByRole("switch", { name: "Use Linear" });
  expect(toggle).toHaveAttribute("aria-checked", "false");
  await u.click(toggle);
  await waitFor(() =>
    expect(
      requestBody(fetchMock, "PUT", `/api/plugins/${LINEAR_PLUGIN_ID}/enabled`)
    ).toEqual({ enabled: true })
  );
});

test("a required plugin cannot be turned off", async () => {
  overview([withPlugin({ installation_policy: "REQUIRED" })]);
  expect(
    await screen.findByRole("switch", { name: "Use Linear" })
  ).toHaveAttribute("aria-disabled", "true");
  expect(screen.getByText(copy.detail.switch.required)).toBeVisible();
  expect(
    screen.queryByRole("button", { name: copy.detail.share.label })
  ).not.toBeInTheDocument();
});

test("the owner shares a private integration plugin", async () => {
  let stored: PluginAccessView = {
    plugin_id: LINEAR_PLUGIN_ID,
    user_shares: [
      { user_id: "u2", email: "ana@example.com", permission: "VIEWER" },
    ],
    group_shares: [],
  };
  const fetchMock = overview(
    [
      withPlugin({
        scope: "personal",
        owner_email: "me@example.com",
        installation_policy: null,
      }),
    ],
    {
      [`/api/plugins/${LINEAR_PLUGIN_ID}/access`]: () => stored,
      [`PUT /api/plugins/${LINEAR_PLUGIN_ID}/access`]: () => {
        stored = {
          plugin_id: LINEAR_PLUGIN_ID,
          user_shares: [],
          group_shares: [],
        };
        return stored;
      },
      "/api/users/shareable": [],
      "/api/settings": {},
    }
  );
  const u = user();
  await u.click(
    await screen.findByRole("button", { name: copy.detail.share.label })
  );
  const dialog = await screen.findByRole("dialog");
  await u.click(
    await within(dialog).findByRole("button", {
      name: "Remove ana@example.com",
    })
  );
  await u.click(
    within(dialog).getByRole("button", { name: copy.share.submit.label })
  );
  await waitFor(() =>
    expect(
      requestBody(fetchMock, "PUT", `/api/plugins/${LINEAR_PLUGIN_ID}/access`)
    ).toEqual({ user_shares: [], group_shares: [] })
  );

  // A reopened dialog shows the saved shares, not the list it loaded first.
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  );
  await u.click(screen.getByRole("button", { name: copy.detail.share.label }));
  const reopened = await screen.findByRole("dialog");
  expect(
    await within(reopened).findByText(copy.share.empty)
  ).toBeInTheDocument();
  expect(
    within(reopened).queryByRole("button", { name: "Remove ana@example.com" })
  ).not.toBeInTheDocument();
});

test("only an organization-wide action manager publishes", async () => {
  const personal = withPlugin({
    scope: "personal",
    owner_email: "me@example.com",
    installation_policy: null,
  });
  overview([personal]);
  expect(
    await screen.findByRole("button", { name: copy.detail.publish.label })
  ).toBeDisabled();
});

test.each([
  [{ plugin_id: LINEAR_PLUGIN_ID, name: "Linear-2" }, "Linear-2"],
  // An older backend answers 204 with no body.
  [null, "Linear"],
])("the owner publishes after the confirmation (%o)", async (body, name) => {
  mockGlobalHolder = true;
  const fetchMock = overview(
    [
      withPlugin({
        scope: "personal",
        owner_email: "me@example.com",
        installation_policy: null,
      }),
    ],
    {
      [`POST /api/plugins/${LINEAR_PLUGIN_ID}/publish`]: body,
    }
  );
  const success = jest.spyOn(toast, "success");
  const u = user();
  await u.click(
    await screen.findByRole("button", { name: copy.detail.publish.label })
  );
  const dialog = await screen.findByRole("dialog");
  await u.click(
    within(dialog).getByRole("button", { name: copy.detail.publish.label })
  );
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) =>
          String(input) === `/api/plugins/${LINEAR_PLUGIN_ID}/publish` &&
          init?.method === "POST"
      )
    ).toBe(true)
  );
  await waitFor(() =>
    expect(success).toHaveBeenCalledWith(
      copy.detail.publish.done.replace("{name}", name)
    )
  );
});
