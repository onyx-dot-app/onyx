import { render, screen, waitFor } from "@tests/setup/test-utils";
import MemberPluginOAuthCompletePage from "@/app/app/plugins/oauth/complete/page";
import { MCPConnectionStatus } from "@/lib/mcp/types";
import { SWR_KEYS } from "@/lib/swr-keys";

let query = new URLSearchParams();

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => "/app/plugins/oauth/complete",
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  useSearchParams: () => query,
}));

beforeEach(() => {
  query = new URLSearchParams({
    pluginKind: "mcp",
    pluginId: "7",
    message: "oauth_connected",
  });
});

afterEach(() => {
  jest.restoreAllMocks();
});

function savedConnection(connected: boolean, roster = "/api/mcp/servers") {
  return jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    if (input === roster) {
      return new Response(
        JSON.stringify({
          mcp_servers: [
            {
              id: 7,
              name: "Team notes",
              server_url: "",
              owner: "",
              auth_type: "OAUTH",
              auth_performer: "PER_USER",
              user_can_authenticate: true,
              connection_status: connected
                ? MCPConnectionStatus.CONNECTED
                : MCPConnectionStatus.NOT_CONNECTED,
              status: "CONNECTED",
              is_public: true,
              groups: [],
              users: [],
              tool_count: 1,
            },
          ],
        })
      );
    }
    if (input === "/api/tool" || input === "/api/user-oauth-token/status")
      return new Response("[]");
    throw new Error(`Unexpected request ${input}`);
  });
}

test("shows success only after the saved member connection is verified", async () => {
  const fetchSpy = savedConnection(true);
  render(<MemberPluginOAuthCompletePage />);
  expect(await screen.findByText("Plugin connected")).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Return to plugins" })
  ).toHaveAttribute("href", "/app/plugins");
  expect(fetchSpy.mock.calls.map(([input]) => input)).toEqual([
    "/api/mcp/servers",
  ]);
});

test("rejects a success query when the backend has no usable connection", async () => {
  savedConnection(false);
  render(<MemberPluginOAuthCompletePage />);
  expect(
    await screen.findByText("Connection not confirmed")
  ).toBeInTheDocument();
});

test.each([0, 8])(
  "verifies the originating agent roster for agent %s",
  async (agentId) => {
    query.set("agentId", String(agentId));
    query.set("surface", "chat");
    const roster = SWR_KEYS.agentMcpServers(agentId);
    const fetchSpy = savedConnection(true, roster);
    render(<MemberPluginOAuthCompletePage />);
    expect(await screen.findByText("Plugin connected")).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledWith(roster);
  }
);

test("verifies the Craft roster for Craft authorization", async () => {
  query.set("surface", "craft");
  const fetchSpy = savedConnection(true, "/api/mcp/servers/craft");
  render(<MemberPluginOAuthCompletePage />);
  expect(await screen.findByText("Plugin connected")).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Return to plugins" })
  ).toHaveAttribute("href", "/craft/v1/plugins");
  expect(fetchSpy).toHaveBeenCalledWith("/api/mcp/servers/craft");
});

test.each(["-1", "", "8oops", "9007199254740992"])(
  "rejects invalid originating agent %s without fetching",
  async (agentId) => {
    query.set("agentId", agentId);
    const fetchSpy = jest.spyOn(global, "fetch");
    render(<MemberPluginOAuthCompletePage />);
    expect(
      await screen.findByText("Connection not confirmed")
    ).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  }
);

test("rejects an uncorrelated direct visit without fetching", async () => {
  query.delete("message");
  const fetchSpy = jest.spyOn(global, "fetch");
  render(<MemberPluginOAuthCompletePage />);
  await waitFor(() =>
    expect(screen.getByText("Connection not confirmed")).toBeInTheDocument()
  );
  expect(fetchSpy).not.toHaveBeenCalled();
});

test.each([true, false])(
  "verifies external app authentication before success, authenticated=%s",
  async (authenticated) => {
    query.set("pluginKind", "external-app");
    const fetchSpy = jest.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            id: 7,
            name: "Project tracker",
            app_type: "CUSTOM",
            credential_keys: [],
            credential_values: {},
            authenticated,
            supports_oauth: true,
          },
        ])
      )
    );
    render(<MemberPluginOAuthCompletePage />);
    expect(
      await screen.findByText(
        authenticated ? "Plugin connected" : "Connection not confirmed"
      )
    ).toBeInTheDocument();
    expect(fetchSpy.mock.calls.map(([input]) => input)).toEqual([
      "/api/build/apps",
    ]);
  }
);
