import { PointerEventsCheckLevel } from "@testing-library/user-event";
import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import MemberPluginDetailPage from "@/sections/plugins/MemberPluginDetailPage";
import messages from "@/i18n/messages/en.json";
import { customFixture } from "@/lib/skills/__fixtures__/picker";
import {
  mockFetch,
  requestBody,
} from "@/sections/integrations/__tests__/integrationFixtures";
import {
  LINEAR_PLUGIN_ID,
  makeMemberAction,
  makeMemberIntegration,
} from "@/sections/plugins/__tests__/memberIntegrationFixtures";
import type { MemberIntegration } from "@/lib/integrations/types";

const copy = messages.plugins.member;
const mockLoadPage = jest.fn();

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
    isGlobalHolder: false,
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
  return { state, reason, moving_credentials: false };
}

afterEach(() => {
  jest.restoreAllMocks();
  mockLoadPage.mockClear();
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
  ]);
  expect(
    await screen.findByText(copy.connection.status.connected)
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Disconnect Connected app" })
  ).toBeVisible();
  expect(screen.getByText(copy.connection.status.notConnected)).toBeVisible();
  expect(screen.getByRole("button", { name: "Connect New app" })).toBeVisible();
  expect(
    screen.getByText("Your admin changed the sign-in settings")
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Reconnect Old app" })
  ).toBeVisible();
  expect(screen.getByText(copy.connection.askAdmin)).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /Shared app/ })
  ).not.toBeInTheDocument();
});

test("the API key form saves the credential fields", async () => {
  const integration = makeMemberIntegration({
    id: 2,
    name: "Reports API",
    auth_method: "api_key",
    credential_fields: [{ key: "token", label: "API Token", secret: true }],
  });
  const fetchMock = open([integration], {
    "PUT /api/integrations/2/connection": status("connected"),
  });
  const u = user();
  await u.click(
    await screen.findByRole("button", { name: "Connect Reports API" })
  );
  const dialog = await screen.findByRole("dialog");
  await u.click(
    within(dialog).getByRole("button", { name: copy.credentials.submit })
  );
  expect(within(dialog).getByText(copy.credentials.required)).toBeVisible();
  await u.type(within(dialog).getByLabelText("API Token"), "secret-1");
  await u.click(
    within(dialog).getByRole("button", { name: copy.credentials.submit })
  );
  await waitFor(() =>
    expect(
      requestBody(fetchMock, "PUT", "/api/integrations/2/connection")
    ).toEqual({ fields: { token: "secret-1" } })
  );
});

test("OAuth starts the user's sign-in in a new tab", async () => {
  const popup = {
    location: { href: "" },
    sessionStorage: { setItem: jest.fn() },
    opener: {},
    close: jest.fn(),
  };
  jest.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
  const fetchMock = open([makeMemberIntegration()], {
    "POST /api/integrations/1/oauth/start": {
      authorization_url: AUTHORIZATION_URL,
    },
  });
  await user().click(
    await screen.findByRole("button", { name: "Connect Linear" })
  );
  await waitFor(() => expect(popup.location.href).toBe(AUTHORIZATION_URL));
  expect(window.open).toHaveBeenCalledWith("about:blank", "_blank");
  expect(
    requestBody(fetchMock, "POST", "/api/integrations/1/oauth/start")
  ).toEqual({ organization: false, return_path: RETURN_PATH });
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

test("Disconnect deletes the user's connection", async () => {
  const fetchMock = open(
    [makeMemberIntegration({ status: status("connected") })],
    { "DELETE /api/integrations/1/connection": status("not_connected") }
  );
  await user().click(
    await screen.findByRole("button", { name: "Disconnect Linear" })
  );
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) =>
          String(url) === "/api/integrations/1/connection" &&
          init?.method === "DELETE"
      )
    ).toBe(true)
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
