import { BroadcastChannel as NativeBroadcastChannel } from "node:worker_threads";
import { render, screen, waitFor } from "@tests/setup/test-utils";
import MemberPluginOAuthCompletePage from "@/app/app/plugins/oauth/complete/page";
import { MCPConnectionStatus } from "@/lib/mcp/types";
import { SWR_KEYS } from "@/lib/swr-keys";

let query = new URLSearchParams();
const originalBroadcastChannel = window.BroadcastChannel;
const channels: NativeBroadcastChannel[] = [];

jest.mock("next/navigation", () => ({
  useSearchParams: () => query,
}));

beforeEach(() => {
  Object.defineProperty(window, "BroadcastChannel", {
    configurable: true,
    value: jest.fn((name: string) => {
      const channel = new NativeBroadcastChannel(name);
      channels.push(channel);
      return channel;
    }),
  });
  query = new URLSearchParams({
    pluginKind: "mcp",
    pluginId: "7",
    attempt: "connection-attempt",
    message: "oauth_connected",
  });
});

afterEach(() => {
  channels.splice(0).forEach((channel) => channel.close());
  Object.defineProperty(window, "BroadcastChannel", {
    configurable: true,
    value: originalBroadcastChannel,
  });
  jest.restoreAllMocks();
});

function opener() {
  const postMessage = jest.fn();
  Object.defineProperty(window, "opener", {
    value: { postMessage },
    configurable: true,
  });
  return postMessage;
}

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

test("reports OAuth completion only after the saved member connection is verified", async () => {
  const postMessage = opener();
  const fetchSpy = savedConnection(true);
  render(<MemberPluginOAuthCompletePage />);
  expect(await screen.findByText("Plugin connected")).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Return to plugins" })
  ).toHaveAttribute("href", "/app/plugins");
  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "onyx:member-plugin-oauth-complete",
      attempt: "connection-attempt",
    },
    window.location.origin
  );
  expect(fetchSpy.mock.calls.map(([input]) => input)).toEqual([
    "/api/mcp/servers",
  ]);
});

test("rejects a success query when the backend has no usable connection", async () => {
  const postMessage = opener();
  savedConnection(false);
  render(<MemberPluginOAuthCompletePage />);
  expect(
    await screen.findByText("Connection not confirmed")
  ).toBeInTheDocument();
  expect(postMessage).not.toHaveBeenCalled();
});

test.each([0, 8])(
  "verifies the originating agent roster for agent %s",
  async (agentId) => {
    query.set("agentId", String(agentId));
    query.set("surface", "chat");
    const postMessage = opener();
    const roster = SWR_KEYS.agentMcpServers(agentId);
    const fetchSpy = savedConnection(true, roster);
    render(<MemberPluginOAuthCompletePage />);
    expect(await screen.findByText("Plugin connected")).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledWith(roster);
    expect(postMessage).toHaveBeenCalledTimes(1);
  }
);

test("verifies the Craft roster for Craft authorization", async () => {
  query.set("surface", "craft");
  const postMessage = opener();
  const fetchSpy = savedConnection(true, "/api/mcp/servers/craft");
  render(<MemberPluginOAuthCompletePage />);
  expect(await screen.findByText("Plugin connected")).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Return to plugins" })
  ).toHaveAttribute("href", "/craft/v1/plugins");
  expect(fetchSpy).toHaveBeenCalledWith("/api/mcp/servers/craft");
  expect(postMessage).toHaveBeenCalledTimes(1);
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

test("a COOP-separated completion verifies the backend and broadcasts without an opener", async () => {
  Object.defineProperty(window, "opener", { value: null, configurable: true });
  const channel = new BroadcastChannel(
    "onyx:member-plugin-oauth-complete:connection-attempt"
  );
  const completion = new Promise<unknown>((resolve) => {
    channel.addEventListener(
      "message",
      (event: MessageEvent<unknown>) => resolve(event.data),
      { once: true }
    );
  });
  const closeSpy = jest.spyOn(NativeBroadcastChannel.prototype, "close");
  const fetchSpy = savedConnection(true);
  render(<MemberPluginOAuthCompletePage />);
  expect(await screen.findByText("Plugin connected")).toBeInTheDocument();
  expect(await completion).toEqual({
    type: "onyx:member-plugin-oauth-complete",
    attempt: "connection-attempt",
  });
  expect(closeSpy).toHaveBeenCalledTimes(1);
  expect(fetchSpy.mock.calls.map(([input]) => input)).toEqual([
    "/api/mcp/servers",
  ]);
});

test("an unusable connection never broadcasts even without an opener", async () => {
  Object.defineProperty(window, "opener", { value: null, configurable: true });
  const postMessage = jest.spyOn(
    NativeBroadcastChannel.prototype,
    "postMessage"
  );
  const fetchSpy = savedConnection(false);
  render(<MemberPluginOAuthCompletePage />);
  expect(
    await screen.findByText("Connection not confirmed")
  ).toBeInTheDocument();
  expect(fetchSpy.mock.calls.map(([input]) => input)).toEqual([
    "/api/mcp/servers",
  ]);
  expect(postMessage).not.toHaveBeenCalled();
});

test.each(["missing", "blocked"])(
  "a verified connection succeeds without an opener and with a %s channel",
  async (availability) => {
    Object.defineProperty(window, "opener", {
      value: null,
      configurable: true,
    });
    Object.defineProperty(window, "BroadcastChannel", {
      value:
        availability === "missing"
          ? undefined
          : jest.fn(() => {
              throw new DOMException("Channel blocked", "SecurityError");
            }),
      configurable: true,
    });
    const fetchSpy = savedConnection(true);
    render(<MemberPluginOAuthCompletePage />);
    expect(await screen.findByText("Plugin connected")).toBeInTheDocument();
    expect(fetchSpy.mock.calls.map(([input]) => input)).toEqual([
      "/api/mcp/servers",
    ]);
  }
);

test("rejects an uncorrelated direct visit without fetching or notifying", async () => {
  const postMessage = opener();
  query.delete("message");
  const fetchSpy = jest.spyOn(global, "fetch");
  render(<MemberPluginOAuthCompletePage />);
  await waitFor(() =>
    expect(screen.getByText("Connection not confirmed")).toBeInTheDocument()
  );
  expect(postMessage).not.toHaveBeenCalled();
  expect(fetchSpy).not.toHaveBeenCalled();
});

test.each([true, false])(
  "verifies external app authentication before notifying, authenticated=%s",
  async (authenticated) => {
    query.set("pluginKind", "external-app");
    const postMessage = opener();
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
    expect(postMessage).toHaveBeenCalledTimes(authenticated ? 1 : 0);
  }
);
