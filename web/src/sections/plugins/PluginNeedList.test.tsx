import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { mockFetch, requestBody } from "@tests/setup/integrationTestUtils";
import type { MemberIntegration } from "@/lib/integrations/types";
import type { PluginNeed, PluginNeedState } from "@/lib/plugins/types";
import PluginNeedList from "@/sections/plugins/PluginNeedList";

const authority = { isGlobalHolder: false, isScopedManager: false };

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => window.location.pathname,
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => authority,
}));
jest.mock("@/lib/integrations/connect", () => ({
  ...jest.requireActual("@/lib/integrations/connect"),
  connectWithOAuth: async () => "connected",
}));

afterEach(() => {
  jest.restoreAllMocks();
  authority.isGlobalHolder = false;
  authority.isScopedManager = false;
});

function need(
  name: string,
  state: PluginNeedState,
  integrationId: number | null = null
): PluginNeed {
  return {
    kind: "mcp",
    name,
    url: state === "not_supported" ? null : `https://example.com/${name}`,
    transport: state === "not_supported" ? "stdio" : "http",
    url_problem: null,
    supported: state !== "not_supported",
    state,
    integration_id: integrationId,
  };
}

function integration(
  id: number,
  state: MemberIntegration["access"]["state"]
): MemberIntegration {
  return {
    id,
    kind: "mcp",
    shape: "mcp_server",
    name: `Integration ${id}`,
    description: null,
    preset_id: null,
    auth_mode: "none",
    auth_method: null,
    credential_fields: [],
    status: { state: "connected", reason: null },
    access: {
      state,
      installation_policy: "AVAILABLE",
      user_choice: null,
      user_enabled: state === "on",
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
  };
}

test("each need shows its state and the one action the member can take", async () => {
  mockFetch({ "/api/integrations": [integration(7, "no_access")] });
  render(
    <PluginNeedList
      interactive
      needs={[
        need("github", "no_access", 7),
        need("linear", "not_added"),
        need("local", "not_supported"),
        need("docs", "turned_off"),
      ]}
    />
  );
  const github = await screen.findByLabelText("github");
  expect(within(github).getByText("No access")).toBeInTheDocument();
  expect(within(github).getByText("Ask an admin")).toBeInTheDocument();
  const linear = screen.getByLabelText("linear");
  expect(within(linear).getByText("Not added")).toBeInTheDocument();
  expect(within(linear).getByText("Ask an admin")).toBeInTheDocument();
  expect(
    within(screen.getByLabelText("local")).getByText("Not supported in Onyx")
  ).toBeInTheDocument();
  expect(
    within(screen.getByLabelText("docs")).getByText("Turned off by your admin")
  ).toBeInTheDocument();
});

test("a need whose URL Onyx dropped gives the reason", async () => {
  mockFetch({ "/api/integrations": [] });
  render(
    <PluginNeedList
      interactive={false}
      needs={[
        {
          ...need("vars", "not_supported"),
          transport: "http",
          url_problem: "variable",
        },
        {
          ...need("keyed", "not_supported"),
          transport: "http",
          url_problem: "credential",
        },
      ]}
    />
  );
  expect(
    await screen.findByText(
      "The URL uses a variable. Onyx does not fill in variables."
    )
  ).toBeInTheDocument();
  expect(
    screen.getByText("The URL has a credential in it. Onyx does not keep it.")
  ).toBeInTheDocument();
  expect(screen.queryByText("No server URL")).not.toBeInTheDocument();
});

test("a user who manages integrations adds a missing one with its name and URL", async () => {
  authority.isGlobalHolder = true;
  mockFetch({ "/api/integrations": [] });
  const user = setupUser();
  render(<PluginNeedList interactive needs={[need("linear", "not_added")]} />);
  await user.click(
    await screen.findByRole("button", { name: "Add the linear integration" })
  );
  await waitFor(() =>
    expect(window.location.pathname).toBe("/admin/integrations/new")
  );
  const params = new URLSearchParams(window.location.search);
  expect(params.get("server_url")).toBe("https://example.com/linear");
  expect(params.get("owner")).toBe("organization");
});

test("a group manager adds a missing integration on the member page", async () => {
  authority.isScopedManager = true;
  mockFetch({ "/api/integrations": [] });
  const user = setupUser();
  render(<PluginNeedList interactive needs={[need("linear", "not_added")]} />);
  await user.click(
    await screen.findByRole("button", { name: "Add the linear integration" })
  );
  await waitFor(() =>
    expect(window.location.pathname).toBe("/app/customize/integrations/new")
  );
  expect(new URLSearchParams(window.location.search).get("owner")).toBeNull();
});

test("Turn on switches the matching integration on and the row reads On", async () => {
  let enabled = false;
  const fetchMock = mockFetch({
    "/api/integrations": () => [integration(3, enabled ? "on" : "turn_on")],
    "PUT /api/integrations/3/enabled": () => {
      enabled = true;
      return integration(3, "on");
    },
  });
  const onChanged = jest.fn();
  const user = setupUser();
  render(
    <PluginNeedList
      interactive
      needs={[need("search", "turn_on", 3)]}
      onChanged={onChanged}
    />
  );
  await user.click(
    await screen.findByRole("button", { name: "Turn on search" })
  );
  const row = screen.getByLabelText("search");
  await waitFor(() => expect(within(row).getByText("On")).toBeInTheDocument());
  expect(requestBody(fetchMock, "PUT", "/api/integrations/3/enabled")).toEqual({
    enabled: true,
  });
  expect(onChanged).toHaveBeenCalledTimes(1);
});

test("a sign-in that connects tells the plugin to refresh", async () => {
  mockFetch({
    "/api/integrations": [
      {
        ...integration(5, "sign_in"),
        auth_mode: "individual",
        auth_method: "oauth2",
        status: { state: "not_connected", reason: null },
      },
    ],
  });
  const onChanged = jest.fn();
  const user = setupUser();
  render(
    <PluginNeedList
      interactive
      needs={[need("drive", "sign_in", 5)]}
      onChanged={onChanged}
    />
  );
  await user.click(
    await screen.findByRole("button", { name: "Connect Integration 5" })
  );

  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
});
