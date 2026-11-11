import { BroadcastChannel as NativeBroadcastChannel } from "node:worker_threads";
import { waitFor } from "@testing-library/react";
import { connectMemberPlugin, type MemberPlugin } from "@/lib/plugins/member";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  MCPConnectionStatus,
  MCPServerStatus,
} from "@/lib/mcp/types";
import { notifyOAuthComplete } from "@/lib/oauth/launch";
import {
  MemberPluginConnectionError,
  runMemberPluginOAuth,
} from "@/lib/plugins/memberConnection";
import { SWR_KEYS } from "@/lib/swr-keys";

const reference = { kind: "mcp", id: 7 } as const;
const authUrl = "https://notes.example/oauth?state=s1";
const originalBroadcastChannel = window.BroadcastChannel;
const channels: NativeBroadcastChannel[] = [];

beforeEach(() => {
  Object.defineProperty(window, "BroadcastChannel", {
    configurable: true,
    value: jest.fn((name: string) => {
      const channel = new NativeBroadcastChannel(name);
      channels.push(channel);
      return channel;
    }),
  });
});

afterEach(() => {
  channels.splice(0).forEach((channel) => channel.close());
  Object.defineProperty(window, "BroadcastChannel", {
    configurable: true,
    value: originalBroadcastChannel,
  });
  delete window.__ONYX_DESKTOP__;
  delete window.__TAURI_INTERNALS__;
  jest.restoreAllMocks();
});

function openPopup() {
  const popup = {
    close: jest.fn(),
    location: { href: "about:blank" },
    sessionStorage: { setItem: jest.fn() },
  };
  jest.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
  return popup;
}

test("the web opens a new tab with the plugin return path", async () => {
  const popup = openPopup();
  const start = jest.fn().mockResolvedValue(authUrl);
  const connected = runMemberPluginOAuth(reference, start, {
    agentId: 5,
    surface: "chat",
  });
  expect(window.open).toHaveBeenCalledWith("about:blank", "_blank");
  await waitFor(() => expect(popup.location.href).toBe(authUrl));
  const returnPath = new URL(start.mock.calls[0]?.[0], window.location.origin);
  expect(returnPath.pathname).toBe("/app/plugins/oauth/complete");
  expect(Object.fromEntries(returnPath.searchParams)).toEqual({
    pluginKind: "mcp",
    pluginId: "7",
    agentId: "5",
    surface: "chat",
  });
  notifyOAuthComplete("s1");
  await connected;
});

test("desktop sends authorization to the system browser and maps a failed callback", async () => {
  const invoke = jest.fn().mockResolvedValue(undefined);
  window.__TAURI_INTERNALS__ = { invoke };
  window.__ONYX_DESKTOP__ = { oauthInBrowser: true };
  const open = jest.spyOn(window, "open");
  const start = jest.fn().mockResolvedValue(authUrl);

  const connected = runMemberPluginOAuth(reference, start);
  await waitFor(() => expect(invoke).toHaveBeenCalledTimes(1));
  expect(open).not.toHaveBeenCalled();
  expect(invoke).toHaveBeenCalledWith("plugin:shell|open", {
    path: "https://notes.example/oauth?state=s1.desktop",
  });
  notifyOAuthComplete("s1");
  await connected;

  const failed = runMemberPluginOAuth(reference, start);
  await waitFor(() => expect(invoke).toHaveBeenCalledTimes(2));
  const detail = { title: "Authorization cancelled", description: "Denied." };
  notifyOAuthComplete("s1", false, undefined, detail);
  await expect(failed).rejects.toMatchObject({
    reason: "not_connected",
    detail,
  });
});

test("maps launch failures to connection errors", async () => {
  jest.spyOn(window, "open").mockReturnValue(null);
  const start = jest.fn();
  await expect(runMemberPluginOAuth(reference, start)).rejects.toMatchObject({
    reason: "popup_blocked",
  });
  expect(start).not.toHaveBeenCalled();

  openPopup();
  await expect(
    runMemberPluginOAuth(reference, async () => {
      throw new MemberPluginConnectionError("unconfigured");
    })
  ).rejects.toMatchObject({ reason: "unconfigured" });
  await expect(
    runMemberPluginOAuth(reference, async () => {
      throw new Error("network");
    })
  ).rejects.toMatchObject({ reason: "request_failed" });

  const controller = new AbortController();
  controller.abort();
  await expect(
    runMemberPluginOAuth(reference, start, { signal: controller.signal })
  ).rejects.toMatchObject({ reason: "cancelled" });
});

test.each([
  {
    connected: true,
    agentId: undefined,
    surface: undefined,
    endpoint: SWR_KEYS.mcpServers,
  },
  {
    connected: false,
    agentId: undefined,
    surface: undefined,
    endpoint: SWR_KEYS.mcpServers,
  },
  {
    connected: true,
    agentId: 5,
    surface: "chat",
    endpoint: SWR_KEYS.agentMcpServers(5),
  },
  {
    connected: true,
    agentId: 0,
    surface: "chat",
    endpoint: SWR_KEYS.agentMcpServers(0),
  },
  {
    connected: true,
    agentId: undefined,
    surface: "craft",
    endpoint: SWR_KEYS.mcpServersCraft,
  },
] as const)(
  "a completed callback still requires backend verification through $endpoint, usable=$connected",
  async ({ connected, agentId, surface, endpoint }) => {
    const popup = openPopup();
    const plugin: MemberPlugin = {
      kind: "mcp",
      server: {
        id: 7,
        name: "Team notes",
        server_url: "",
        owner: "",
        status: MCPServerStatus.CONNECTED,
        is_public: true,
        groups: [],
        users: [],
        tool_count: 1,
        auth_type: MCPAuthenticationType.OAUTH,
        auth_performer: MCPAuthenticationPerformer.PER_USER,
        connection_status: MCPConnectionStatus.NOT_CONNECTED,
      },
      tools: [],
      connection: { kind: "oauth" },
    };
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockImplementation(async (input) => {
        if (input === "/api/mcp/oauth/connect") {
          return new Response(
            JSON.stringify({
              status: "authorization_required",
              authorization_url: authUrl,
              server_id: 7,
              redirect_url: "/app",
            })
          );
        }
        if (input === endpoint) {
          return new Response(
            JSON.stringify({
              mcp_servers: [
                {
                  ...plugin.server,
                  connection_status: connected
                    ? MCPConnectionStatus.CONNECTED
                    : MCPConnectionStatus.NOT_CONNECTED,
                },
              ],
            })
          );
        }
        return new Response("[]");
      });
    const promise = connectMemberPlugin(plugin, undefined, {
      agentId,
      surface,
    });
    const outcome = connected
      ? expect(promise).resolves.toBeUndefined()
      : expect(promise).rejects.toMatchObject({ reason: "not_connected" });
    await waitFor(() => expect(popup.location.href).toBe(authUrl));
    notifyOAuthComplete("s1");
    await outcome;
    expect(fetchSpy.mock.calls.map(([input]) => input)).toEqual([
      "/api/mcp/oauth/connect",
      endpoint,
    ]);
  }
);
