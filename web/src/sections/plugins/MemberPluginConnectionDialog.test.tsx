import {
  act,
  deferred,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import MemberPluginConnectionDialog from "@/sections/plugins/MemberPluginConnectionDialog";
import { MCPAuthenticationType, MCPConnectionStatus } from "@/lib/mcp/types";
import type { MemberPlugin } from "@/lib/plugins/member";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  jsonResponse,
  memberServer,
  storedMcpTool,
  memberApp,
} from "@/sections/plugins/__tests__/memberPluginFixtures";

const credentialPlugin: MemberPlugin = {
  kind: "mcp",
  server: memberServer({
    auth_type: MCPAuthenticationType.API_TOKEN,
    connection_status: MCPConnectionStatus.NOT_CONNECTED,
  }),
  tools: [storedMcpTool],
  connection: { kind: "credentials", fields: ["api_key"], thenOAuth: false },
};

afterEach(() => jest.restoreAllMocks());

test("external-app OAuth uses the shared popup flow and reports blocked popups", async () => {
  jest.spyOn(window, "open").mockReturnValue(null);
  const requests = jest.spyOn(global, "fetch");
  render(
    <MemberPluginConnectionDialog
      plugin={{
        kind: "external-app",
        app: memberApp(),
        connection: { kind: "oauth" },
      }}
      open
      onClose={jest.fn()}
      onConnected={jest.fn()}
    />
  );
  await setupUser().click(
    screen.getByRole("button", { name: "Continue to Workspace GitHub" })
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Allow popups and try again."
  );
  expect(requests).not.toHaveBeenCalled();
});

test("external app credentials reuse the app service and authoritative status check", async () => {
  const connected = jest.fn();
  const app = memberApp({
    supports_oauth: false,
    credential_keys: ["api_key"],
  });
  const requests = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) => {
      if (String(input) === "/api/build/apps/7/credentials")
        return jsonResponse({});
      if (String(input) === "/api/build/apps")
        return jsonResponse([{ ...app, authenticated: true }]);
      throw new Error(`Unexpected request ${String(input)}`);
    });
  render(
    <MemberPluginConnectionDialog
      plugin={{
        kind: "external-app",
        app,
        connection: {
          kind: "credentials",
          fields: ["api_key"],
          thenOAuth: false,
        },
      }}
      open
      onClose={jest.fn()}
      onConnected={connected}
    />
  );
  const user = setupUser();
  await user.type(screen.getByLabelText("api_key"), "personal-app-key");
  await user.click(screen.getByRole("button", { name: /^Connect$/ }));
  await waitFor(() => expect(connected).toHaveBeenCalledTimes(1));
  expect(requests).toHaveBeenCalledWith(
    "/api/build/apps/7/credentials",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        user_credentials: { api_key: "personal-app-key" },
      }),
    })
  );
});

test.each([
  {
    label: "directory",
    agentId: undefined,
    surface: "all" as const,
    roster: SWR_KEYS.mcpServers,
  },
  {
    label: "shared agent",
    agentId: 8,
    surface: "chat" as const,
    roster: SWR_KEYS.agentMcpServers(8),
  },
  {
    label: "Craft",
    agentId: undefined,
    surface: "craft" as const,
    roster: SWR_KEYS.mcpServersCraft,
  },
])(
  "saves credentials and confirms the connection in its $label roster",
  async ({ agentId, surface, roster }) => {
    const connected = jest.fn();
    const requests = jest
      .spyOn(global, "fetch")
      .mockImplementation(async (input) => {
        if (String(input) === "/api/mcp/user-credentials")
          return jsonResponse({});
        if (String(input) === roster)
          return jsonResponse({
            mcp_servers: [
              memberServer({ auth_type: MCPAuthenticationType.API_TOKEN }),
            ],
          });
        if (String(input) === "/api/tool") return jsonResponse([storedMcpTool]);
        if (String(input) === "/api/user-oauth-token/status")
          return jsonResponse([]);
        throw new Error(`Unexpected request ${String(input)}`);
      });
    render(
      <MemberPluginConnectionDialog
        plugin={credentialPlugin}
        agentId={agentId}
        surface={surface}
        open
        onClose={jest.fn()}
        onConnected={connected}
      />
    );
    const user = setupUser();
    const submit = screen.getByRole("button", { name: "Connect" });
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText("api_key"), "member-api-key");
    await user.click(submit);
    await waitFor(() => expect(connected).toHaveBeenCalledTimes(1));
    expect(requests).toHaveBeenCalledWith(
      "/api/mcp/user-credentials",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          server_id: 7,
          credentials: { api_key: "member-api-key" },
          transport: "STREAMABLE_HTTP",
        }),
      })
    );
  }
);

test("a blocked sign-in popup leaves the dialog open with an actionable error", async () => {
  jest.spyOn(window, "open").mockReturnValue(null);
  const connected = jest.fn();
  render(
    <MemberPluginConnectionDialog
      plugin={{ ...credentialPlugin, connection: { kind: "oauth" } }}
      open
      onClose={jest.fn()}
      onConnected={connected}
    />
  );
  await setupUser().click(
    screen.getByRole("button", { name: "Continue to Linear" })
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Allow popups and try again."
  );
  expect(connected).not.toHaveBeenCalled();
});

test("closing and reopening discards credential drafts", async () => {
  const close = jest.fn();
  const props = {
    plugin: credentialPlugin,
    onClose: close,
    onConnected: jest.fn(),
  };
  const { rerender } = render(<MemberPluginConnectionDialog {...props} open />);
  const user = setupUser();
  await user.type(screen.getByLabelText("api_key"), "discarded-key");
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(close).toHaveBeenCalledTimes(1);
  rerender(<MemberPluginConnectionDialog {...props} open={false} />);
  rerender(<MemberPluginConnectionDialog {...props} open />);
  expect(screen.getByLabelText("api_key")).toHaveValue("");
});

test("Cancel aborts an active OAuth attempt and closes its reserved window", async () => {
  const authorization = deferred<Response>();
  jest.spyOn(window, "open").mockReturnValue(window);
  const closePopup = jest.spyOn(window, "close").mockImplementation(() => {});
  jest.spyOn(global, "fetch").mockReturnValue(authorization.promise);
  const close = jest.fn();
  const connected = jest.fn();
  render(
    <MemberPluginConnectionDialog
      plugin={{ ...credentialPlugin, connection: { kind: "oauth" } }}
      open
      onClose={close}
      onConnected={connected}
    />
  );
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Continue to Linear" }));
  expect(screen.getByRole("button", { name: "Connecting..." })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(close).toHaveBeenCalledTimes(1);
  expect(closePopup).toHaveBeenCalledTimes(1);
  await act(async () =>
    authorization.resolve(jsonResponse({ status: "already_authenticated" }))
  );
  expect(connected).not.toHaveBeenCalled();
});

test.each(["workspace", "session", "none"] as const)(
  "%s connections describe their ownership without sign-in controls",
  (ownership) => {
    render(
      <MemberPluginConnectionDialog
        plugin={{
          ...credentialPlugin,
          connection: { kind: "connected", ownership },
        }}
        open
        onClose={jest.fn()}
        onConnected={jest.fn()}
      />
    );
    expect(
      screen.queryByRole("button", { name: "Connect" })
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText("api_key")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Done" })).toBeVisible();
  }
);
