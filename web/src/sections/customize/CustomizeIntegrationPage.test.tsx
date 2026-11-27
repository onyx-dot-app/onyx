import { PointerEventsCheckLevel } from "@testing-library/user-event";
import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { toast } from "@opal/layouts";
import { mockFetch, requestBody } from "@tests/setup/integrationTestUtils";
import {
  makeAccess,
  makeMemberAction,
  makeMemberIntegration,
} from "@tests/setup/memberIntegrationTestUtils";
import CustomizeIntegrationPage from "@/sections/customize/CustomizeIntegrationPage";
import type {
  IntegrationSharesView,
  MemberIntegration,
} from "@/lib/integrations/types";
import messages from "@/i18n/messages/en.json";

const copy = messages.customize.integrationPage;
const menuCopy = messages.integrations.menu;
const shareCopy = messages.integrations.share;
const AUTHORIZATION_URL = "https://linear.app/oauth/authorize?state=attempt-1";
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

function user() {
  return setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
}

function open(
  integration: MemberIntegration,
  extra: Record<string, unknown> = {},
  tab: string | null = null
) {
  window.history.replaceState(
    null,
    "",
    `/app/customize/integrations/${integration.id}${tab ? `?tab=${tab}` : ""}`
  );
  const fetchMock = mockFetch({
    "/api/integrations": [integration],
    ...extra,
  });
  render(<CustomizeIntegrationPage integrationId={integration.id} />);
  return fetchMock;
}

const connected = { state: "connected", reason: null } as const;

afterEach(() => {
  jest.restoreAllMocks();
  mockLoadPage.mockClear();
  mockGlobalHolder = false;
});

// ── Overview ─────────────────────────────────────────────────────────────────

test("shows the status, Connect and the admin setting of each action", async () => {
  open(makeMemberIntegration(), {
    "/api/action-policies/integration/1": {
      users_can_save_always_allow: false,
      actions: [
        makeMemberAction({
          key: "create_issue",
          display_name: "Create issue",
          effective_admin_policy: "blocked",
        }),
        makeMemberAction({
          key: "list_issues",
          display_name: "List issues",
          effective_admin_policy: "allow",
        }),
        makeMemberAction({
          key: "update_issue",
          display_name: "Update issue",
          effective_admin_policy: "ask",
        }),
      ],
    },
  });
  expect(await screen.findByText("Not connected")).toBeVisible();
  expect(screen.getByRole("button", { name: "Connect Linear" })).toBeVisible();

  await user().click(screen.getByRole("tab", { name: copy.tabs.actions }));
  expect(await screen.findByText("Create issue")).toBeVisible();
  expect(screen.getByText("Blocked")).toBeVisible();
  expect(screen.getByText("Allow")).toBeVisible();
  expect(screen.getByText("Ask")).toBeVisible();
  expect(screen.queryByRole("switch")).not.toBeInTheDocument();
});

test("an integration the user cannot see shows the error state", async () => {
  window.history.replaceState(null, "", "/app/customize/integrations/9");
  mockFetch({ "/api/integrations": [makeMemberIntegration()] });
  render(<CustomizeIntegrationPage integrationId={9} />);
  expect(await screen.findByText(copy.loadFailed)).toBeVisible();
});

test("the member turns an integration on", async () => {
  const fetchMock = open(
    makeMemberIntegration({
      status: connected,
      access: makeAccess({
        state: "turn_on",
        user_choice: null,
        user_enabled: false,
      }),
    }),
    { "PUT /api/integrations/1/enabled": makeMemberIntegration() }
  );
  const toggle = await screen.findByRole("switch", { name: "Use Linear" });
  expect(toggle).toHaveAttribute("aria-checked", "false");
  await user().click(toggle);
  await waitFor(() =>
    expect(
      requestBody(fetchMock, "PUT", "/api/integrations/1/enabled")
    ).toEqual({ enabled: true })
  );
});

test("turning on an integration with no sign-in opens the sign-in; Cancel keeps it off", async () => {
  const fetchMock = open(
    makeMemberIntegration({
      auth_method: "api_key",
      credential_fields: [{ key: "token", label: "API Token", secret: true }],
      access: makeAccess({
        state: "turn_on",
        user_choice: null,
        user_enabled: false,
      }),
    }),
    { "PUT /api/integrations/1/enabled": makeMemberIntegration() }
  );
  const u = user();
  await u.click(await screen.findByRole("switch", { name: "Use Linear" }));
  const dialog = await screen.findByRole("dialog");
  await u.click(
    within(dialog).getByRole("button", {
      name: messages.plugins.member.credentials.cancel.label,
    })
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  );
  expect(() =>
    requestBody(fetchMock, "PUT", "/api/integrations/1/enabled")
  ).toThrow();
  expect(screen.getByRole("switch", { name: "Use Linear" })).toHaveAttribute(
    "aria-checked",
    "false"
  );
});

test("turning on an integration with no sign-in turns it on after the API key connects", async () => {
  const fetchMock = open(
    makeMemberIntegration({
      auth_method: "api_key",
      credential_fields: [{ key: "token", label: "API Token", secret: true }],
      access: makeAccess({
        state: "turn_on",
        user_choice: null,
        user_enabled: false,
      }),
    }),
    {
      "PUT /api/integrations/1/connection": {
        state: "connected",
        reason: null,
      },
      "PUT /api/integrations/1/enabled": makeMemberIntegration(),
    }
  );
  const u = user();
  await u.click(await screen.findByRole("switch", { name: "Use Linear" }));
  const dialog = await screen.findByRole("dialog");
  await u.type(within(dialog).getByLabelText("API Token"), "secret-1");
  await u.click(
    within(dialog).getByRole("button", {
      name: messages.plugins.member.credentials.submit.label,
    })
  );
  await waitFor(() =>
    expect(
      requestBody(fetchMock, "PUT", "/api/integrations/1/enabled")
    ).toEqual({ enabled: true })
  );
});

test("a blocked tab moves the OAuth sign-in here without turning the integration on", async () => {
  jest.spyOn(window, "open").mockReturnValue(null);
  const fetchMock = open(
    makeMemberIntegration({
      access: makeAccess({
        state: "turn_on",
        user_choice: null,
        user_enabled: false,
      }),
    }),
    {
      "POST /api/integrations/1/oauth/start": {
        authorization_url: AUTHORIZATION_URL,
      },
    }
  );
  await user().click(await screen.findByRole("switch", { name: "Use Linear" }));
  await waitFor(() =>
    expect(mockLoadPage).toHaveBeenCalledWith(AUTHORIZATION_URL)
  );
  expect(() =>
    requestBody(fetchMock, "PUT", "/api/integrations/1/enabled")
  ).toThrow();
});

describe("after a sign-in that moved here", () => {
  const turnOn = makeAccess({
    state: "turn_on",
    user_choice: null,
    user_enabled: false,
  });

  beforeEach(() => {
    window.sessionStorage.setItem("onyx:integration-pending-turn-on", "1");
  });

  afterEach(() => window.sessionStorage.clear());

  test("a connected integration turns on", async () => {
    const fetchMock = open(
      makeMemberIntegration({ status: connected, access: turnOn }),
      { "PUT /api/integrations/1/enabled": makeMemberIntegration() }
    );
    await waitFor(() =>
      expect(
        requestBody(fetchMock, "PUT", "/api/integrations/1/enabled")
      ).toEqual({ enabled: true })
    );
    expect(
      window.sessionStorage.getItem("onyx:integration-pending-turn-on")
    ).toBeNull();
  });

  test("a cancelled sign-in keeps the integration off", async () => {
    const fetchMock = open(
      makeMemberIntegration({
        status: { state: "not_connected", reason: null },
        access: turnOn,
      })
    );
    expect(
      await screen.findByRole("switch", { name: "Use Linear" })
    ).toHaveAttribute("aria-checked", "false");
    expect(() =>
      requestBody(fetchMock, "PUT", "/api/integrations/1/enabled")
    ).toThrow();
    expect(
      window.sessionStorage.getItem("onyx:integration-pending-turn-on")
    ).toBeNull();
  });
});

test("a Required integration cannot be turned off", async () => {
  open(
    makeMemberIntegration({
      status: connected,
      access: makeAccess({ state: "on", installation_policy: "REQUIRED" }),
    })
  );
  expect(
    await screen.findByRole("switch", { name: "Use Linear" })
  ).toHaveAttribute("aria-disabled", "true");
  expect(screen.getByText(copy.overview.switch.required)).toBeVisible();
});

test("an integration with no access shows the reason and the owner", async () => {
  open(
    makeMemberIntegration({
      access: makeAccess({
        state: "no_access",
        user_enabled: false,
        owner_email: "ana@example.com",
        shared_with_everyone: false,
      }),
    })
  );
  expect(
    await screen.findByText(
      "No access: ana@example.com has not shared it with you."
    )
  ).toBeVisible();
  expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("tab", { name: copy.tabs.actions })
  ).not.toBeInTheDocument();
});

// ── Connection ───────────────────────────────────────────────────────────────

test("the header offers Disconnect after the API key form connects", async () => {
  const integration = makeMemberIntegration({
    id: 2,
    name: "Reports API",
    auth_method: "api_key",
    credential_fields: [{ key: "token", label: "API Token", secret: true }],
  });
  let state: MemberIntegration["status"]["state"] = "not_connected";
  open(integration, {
    "/api/integrations": () => [
      { ...integration, status: { state, reason: null } },
    ],
    "PUT /api/integrations/2/connection": () => {
      state = "connected";
      return { state, reason: null };
    },
  });
  const u = user();
  const connect = await screen.findByRole("button", {
    name: "Connect Reports API",
  });
  // The connection lives in the header; there is no Configuration tab.
  expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
    copy.tabs.overview,
    copy.tabs.actions,
  ]);
  await u.click(connect);
  const dialog = await screen.findByRole("dialog");
  await u.type(within(dialog).getByLabelText("API Token"), "secret-1");
  await u.click(
    within(dialog).getByRole("button", {
      name: messages.plugins.member.credentials.submit.label,
    })
  );
  expect(
    await screen.findByRole("button", { name: "Disconnect Reports API" })
  ).toBeVisible();
});

test.each(["connected", "needs_reconnect"] as const)(
  "a turned off integration keeps Disconnect for a %s connection",
  async (state) => {
    const fetchMock = open(
      makeMemberIntegration({
        status: { state, reason: null },
        access: makeAccess({ state: "turned_off" }),
      }),
      { "DELETE /api/integrations/1/connection": { state: "not_connected" } }
    );
    expect(await screen.findByText("Turned off by an admin.")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Reconnect Linear" })
    ).not.toBeInTheDocument();
    await user().click(
      screen.getByRole("button", { name: "Disconnect Linear" })
    );
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith("/api/integrations/1/connection") &&
            init?.method === "DELETE"
        )
      ).toBe(true)
    );
  }
);

test("the overview shows why the user must reconnect and offers Disconnect", async () => {
  open(
    makeMemberIntegration({
      status: { state: "needs_reconnect", reason: "The token expired." },
    })
  );
  expect(await screen.findByText("The token expired.")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Reconnect Linear" })
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Disconnect Linear" })
  ).toBeVisible();
});

test("a broken Onyx login asks the member to sign in again, not the admin", async () => {
  open(
    makeMemberIntegration({
      auth_method: "onyx_login",
      status: {
        state: "needs_reconnect",
        reason: "Sign in to Onyx again to use Linear.",
      },
    })
  );
  expect(
    await screen.findByText("Sign in to Onyx again to use Linear.")
  ).toBeVisible();
  expect(
    screen.queryByText(messages.plugins.member.connection.askAdmin)
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Disconnect Linear" })
  ).toBeVisible();
});

test("OAuth continues in this tab when the browser blocks the new tab", async () => {
  jest.spyOn(window, "open").mockReturnValue(null);
  open(makeMemberIntegration(), {
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

// ── Don't ask me ──────────────────────────────────────────────────────────────

test("an action that asks offers Don't ask me", async () => {
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
    makeMemberIntegration({
      status: connected,
      users_can_save_always_allow: true,
    }),
    {
      "/api/action-policies/integration/1": policies,
      "PUT /api/action-policies/integration/1": {
        ...policies,
        actions: [
          { ...policies.actions[0], user_policy: "allow" },
          policies.actions[1],
        ],
      },
    },
    "actions"
  );
  const toggle = await screen.findByRole("switch", {
    name: "Don't ask me for Create issue",
  });
  expect(
    screen.queryByRole("switch", { name: "Don't ask me for List issues" })
  ).not.toBeInTheDocument();
  // The policy is a badge; only the action that asks gets the labelled switch.
  expect(screen.getByText("Ask")).toBeVisible();
  expect(screen.getByText("Allow")).toBeVisible();
  expect(screen.getAllByText("Don't ask me")).toHaveLength(1);
  await user().click(toggle);
  await waitFor(() =>
    expect(
      requestBody(fetchMock, "PUT", "/api/action-policies/integration/1")
    ).toEqual({ actions: { create_issue: "allow" } })
  );
  await waitFor(() => expect(toggle).toBeChecked());
});

// ── Share and publish ────────────────────────────────────────────────────────

const ownPrivate = makeMemberIntegration({
  status: connected,
  access: makeAccess({
    state: "on",
    installation_policy: "NOT_AVAILABLE",
    owner_email: "me@example.com",
    is_owner: true,
    can_manage: true,
    shared_with_everyone: false,
  }),
});

async function openMenu() {
  await user().click(
    await screen.findByRole("button", {
      name: menuCopy.label.replace("{name}", "Linear"),
    })
  );
}

test("the owner shares a private integration with no permission choice", async () => {
  let stored: IntegrationSharesView = {
    integration_id: 1,
    user_shares: [{ user_id: "u2", email: "ana@example.com" }],
    group_shares: [],
  };
  const fetchMock = open(ownPrivate, {
    "/api/integrations/1/access": () => stored,
    "PUT /api/integrations/1/access": () => {
      stored = { integration_id: 1, user_shares: [], group_shares: [] };
      return stored;
    },
    "/api/users/shareable": [],
    "/api/settings": {},
  });
  const u = user();
  await openMenu();
  await u.click(await screen.findByRole("menuitem", { name: menuCopy.share }));
  const dialog = await screen.findByRole("dialog");
  await u.click(
    await within(dialog).findByRole("button", {
      name: "Remove ana@example.com",
    })
  );
  expect(within(dialog).queryByRole("combobox", { name: /permission/i })).toBe(
    null
  );
  await u.click(
    within(dialog).getByRole("button", { name: shareCopy.submit.label })
  );
  await waitFor(() =>
    expect(requestBody(fetchMock, "PUT", "/api/integrations/1/access")).toEqual(
      { user_ids: [], group_ids: [] }
    )
  );
});

test("an integration of everyone has no share menu", async () => {
  open(
    makeMemberIntegration({
      status: connected,
      access: makeAccess({ state: "on", can_manage: true }),
    })
  );
  expect(
    await screen.findByRole("switch", { name: "Use Linear" })
  ).toBeVisible();
  expect(
    screen.queryByRole("button", {
      name: menuCopy.label.replace("{name}", "Linear"),
    })
  ).not.toBeInTheDocument();
});

test("an organization-wide action manager publishes after the confirmation", async () => {
  mockGlobalHolder = true;
  const fetchMock = open(ownPrivate, {
    "POST /api/integrations/1/publish": { installation_policy: "AVAILABLE" },
  });
  const success = jest.spyOn(toast, "success");
  const u = user();
  await openMenu();
  await u.click(
    await screen.findByRole("menuitem", { name: menuCopy.publish.label })
  );
  const dialog = await screen.findByRole("dialog");
  await u.click(
    within(dialog).getByRole("button", { name: menuCopy.publish.label })
  );
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) =>
          String(input) === "/api/integrations/1/publish" &&
          init?.method === "POST"
      )
    ).toBe(true)
  );
  await waitFor(() =>
    expect(success).toHaveBeenCalledWith(
      menuCopy.publish.done.replace("{name}", "Linear")
    )
  );
});
