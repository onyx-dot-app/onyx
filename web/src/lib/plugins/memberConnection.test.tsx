import { BroadcastChannel as NativeBroadcastChannel } from "node:worker_threads";
import { waitFor } from "@testing-library/react";
import { connectMemberPlugin, type MemberPlugin } from "@/lib/plugins/member";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  MCPConnectionStatus,
  MCPServerStatus,
} from "@/lib/mcp/types";
import { runMemberPluginOAuth } from "@/lib/plugins/memberConnection";
import { SWR_KEYS } from "@/lib/swr-keys";

const reference = { kind: "mcp", id: 7 } as const;
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

function openPopup() {
  const popup = {
    closed: false,
    close: jest.fn(),
    location: { href: "about:blank" },
  };
  const popupWindow = popup as unknown as Window;
  jest.spyOn(window, "open").mockReturnValue(popupWindow);
  return { popup, popupWindow };
}

afterEach(() => {
  channels.splice(0).forEach((channel) => channel.close());
  Object.defineProperty(window, "BroadcastChannel", {
    configurable: true,
    value: originalBroadcastChannel,
  });
  jest.restoreAllMocks();
  jest.useRealTimers();
});

test("reports blocked popup without starting authorization", async () => {
  jest.spyOn(window, "open").mockReturnValue(null);
  const start = jest.fn();
  await expect(runMemberPluginOAuth(reference, start)).rejects.toMatchObject({
    reason: "popup_blocked",
  });
  expect(start).not.toHaveBeenCalled();
});

test("accepts only the correlated same-origin popup and cleans up after completion", async () => {
  const { popup, popupWindow } = openPopup();
  const removeSpy = jest.spyOn(window, "removeEventListener");
  let returnPath = "";
  const promise = runMemberPluginOAuth(reference, async (path) => {
    returnPath = path;
    return "https://notes.example/oauth";
  });
  expect(window.open).toHaveBeenCalledWith("about:blank", "_blank");
  await Promise.resolve();
  const attempt = new URL(returnPath, window.location.origin).searchParams.get(
    "attempt"
  );
  const data = { type: "onyx:member-plugin-oauth-complete", attempt };
  const emit = (
    origin: string,
    source: MessageEventSource | null,
    payload = data
  ) =>
    window.dispatchEvent(
      new MessageEvent("message", { origin, source, data: payload })
    );
  emit("https://other.example", popupWindow);
  emit(window.location.origin, window);
  emit(window.location.origin, popupWindow, { ...data, attempt: "wrong" });
  expect(popup.close).not.toHaveBeenCalled();
  emit(window.location.origin, popupWindow);
  await promise;
  expect(popup.location.href).toBe("https://notes.example/oauth");
  expect(popup.close).toHaveBeenCalledTimes(1);
  expect(removeSpy).toHaveBeenCalledWith("message", expect.any(Function));
});

test("a closed popup reference stays pending for a COOP-separated completion", async () => {
  jest.useFakeTimers();
  const { popup } = openPopup();
  let returnPath = "";
  const promise = runMemberPluginOAuth(reference, async (path) => {
    returnPath = path;
    return "https://notes.example/oauth";
  });
  await Promise.resolve();
  popup.closed = true;
  jest.advanceTimersByTime(300);
  expect(popup.close).not.toHaveBeenCalled();
  const attempt = new URL(returnPath, window.location.origin).searchParams.get(
    "attempt"
  );
  const channel = new BroadcastChannel(
    `onyx:member-plugin-oauth-complete:${attempt}`
  );
  channel.postMessage({ type: "onyx:member-plugin-oauth-complete", attempt });
  await promise;
  expect(popup.close).toHaveBeenCalledTimes(1);
  expect(jest.getTimerCount()).toBe(0);
});

test("broadcast completion requires the attempt's channel and matching payload", async () => {
  const { popup } = openPopup();
  let returnPath = "";
  const promise = runMemberPluginOAuth(reference, async (path) => {
    returnPath = path;
    return "https://notes.example/oauth";
  });
  const parentChannel = channels[0];
  if (!parentChannel) throw new Error("Missing completion channel");
  const attempt = new URL(returnPath, window.location.origin).searchParams.get(
    "attempt"
  );
  const otherChannel = new BroadcastChannel(
    "onyx:member-plugin-oauth-complete:other-attempt"
  );
  otherChannel.postMessage({
    type: "onyx:member-plugin-oauth-complete",
    attempt,
  });
  const sender = new BroadcastChannel(
    `onyx:member-plugin-oauth-complete:${attempt}`
  );
  const wrongMessageReceived = new Promise<void>((resolve) => {
    parentChannel.addEventListener("message", () => resolve(), { once: true });
  });
  sender.postMessage({
    type: "onyx:member-plugin-oauth-complete",
    attempt: "other-attempt",
  });
  await wrongMessageReceived;
  expect(popup.close).not.toHaveBeenCalled();
  const closeSpy = jest.spyOn(parentChannel, "close");
  const removeSpy = jest.spyOn(parentChannel, "removeEventListener");
  sender.postMessage({ type: "onyx:member-plugin-oauth-complete", attempt });
  await promise;
  expect(popup.close).toHaveBeenCalledTimes(1);
  expect(closeSpy).toHaveBeenCalledTimes(1);
  expect(removeSpy).toHaveBeenCalledWith("message", expect.any(Function));
});

test("an abort cancels initiation and prevents late popup navigation", async () => {
  jest.useFakeTimers();
  const { popup } = openPopup();
  const controller = new AbortController();
  const removeWindowListener = jest.spyOn(window, "removeEventListener");
  const removeAbortListener = jest.spyOn(
    controller.signal,
    "removeEventListener"
  );
  let authorize: ((url: string) => void) | undefined;
  const promise = runMemberPluginOAuth(
    reference,
    () =>
      new Promise((resolve) => {
        authorize = resolve;
      }),
    { signal: controller.signal }
  );
  const rejected = expect(promise).rejects.toMatchObject({
    reason: "cancelled",
  });
  const channel = channels[0];
  if (!channel) throw new Error("Missing completion channel");
  const closeSpy = jest.spyOn(channel, "close");
  const removeSpy = jest.spyOn(channel, "removeEventListener");
  controller.abort();
  authorize?.("https://notes.example/oauth");
  await rejected;
  expect(popup.location.href).toBe("about:blank");
  expect(popup.close).toHaveBeenCalledTimes(1);
  expect(closeSpy).toHaveBeenCalledTimes(1);
  expect(removeSpy).toHaveBeenCalledWith("message", expect.any(Function));
  expect(removeWindowListener).toHaveBeenCalledWith(
    "message",
    expect.any(Function)
  );
  expect(removeAbortListener).toHaveBeenCalledWith(
    "abort",
    expect.any(Function)
  );
  expect(jest.getTimerCount()).toBe(0);
});

test.each(["missing", "blocked"])(
  "postMessage completion works with a %s BroadcastChannel",
  async (availability) => {
    Object.defineProperty(window, "BroadcastChannel", {
      configurable: true,
      value:
        availability === "missing"
          ? undefined
          : jest.fn(() => {
              throw new DOMException("Channel blocked", "SecurityError");
            }),
    });
    const { popup, popupWindow } = openPopup();
    let returnPath = "";
    const promise = runMemberPluginOAuth(reference, async (path) => {
      returnPath = path;
      return "https://notes.example/oauth";
    });
    const attempt = new URL(
      returnPath,
      window.location.origin
    ).searchParams.get("attempt");
    window.dispatchEvent(
      new MessageEvent("message", {
        origin: window.location.origin,
        source: popupWindow,
        data: { type: "onyx:member-plugin-oauth-complete", attempt },
      })
    );
    await promise;
    expect(popup.close).toHaveBeenCalledTimes(1);
  }
);

test("a detached popup without a channel waits until the timeout", async () => {
  jest.useFakeTimers();
  Object.defineProperty(window, "BroadcastChannel", {
    configurable: true,
    value: undefined,
  });
  const { popup } = openPopup();
  const promise = runMemberPluginOAuth(
    reference,
    async () => "https://notes.example/oauth"
  );
  const rejected = expect(promise).rejects.toMatchObject({
    reason: "timed_out",
  });
  await Promise.resolve();
  popup.closed = true;
  jest.advanceTimersByTime(300);
  expect(popup.close).not.toHaveBeenCalled();
  jest.advanceTimersByTime(299700);
  await rejected;
  expect(popup.close).toHaveBeenCalledTimes(1);
  expect(jest.getTimerCount()).toBe(0);
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
    connected: false,
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
  "a broadcast requires backend verification through $endpoint, usable=$connected",
  async ({ connected, agentId, surface, endpoint }) => {
    const { popup } = openPopup();
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
    let attempt: string | null = null;
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockImplementation(async (input, init) => {
        if (input === "/api/mcp/oauth/connect") {
          const body: { return_path: string } = JSON.parse(String(init?.body));
          attempt = new URL(
            body.return_path,
            window.location.origin
          ).searchParams.get("attempt");
          const query = new URL(body.return_path, window.location.origin)
            .searchParams;
          expect(query.get("agentId")).toBe(
            agentId === undefined ? null : String(agentId)
          );
          expect(query.get("surface")).toBe(surface ?? null);
          return new Response(
            JSON.stringify({
              status: "authorization_required",
              authorization_url: "https://notes.example/oauth",
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
    await waitFor(() =>
      expect(popup.location.href).toBe("https://notes.example/oauth")
    );
    new BroadcastChannel(
      `onyx:member-plugin-oauth-complete:${attempt}`
    ).postMessage({
      type: "onyx:member-plugin-oauth-complete",
      attempt,
    });
    await outcome;
    expect(fetchSpy.mock.calls.map(([input]) => input)).toEqual([
      "/api/mcp/oauth/connect",
      endpoint,
    ]);
    expect(popup.close).toHaveBeenCalledTimes(1);
  }
);

test("timeouts and failed initiation close the popup and release timers", async () => {
  jest.useFakeTimers();
  const { popup } = openPopup();
  const timedOut = runMemberPluginOAuth(reference, () => new Promise(() => {}));
  const rejected = expect(timedOut).rejects.toMatchObject({
    reason: "timed_out",
  });
  jest.advanceTimersByTime(300000);
  await rejected;
  expect(jest.getTimerCount()).toBe(0);
  await expect(
    runMemberPluginOAuth(reference, async () => {
      throw new Error("failed");
    })
  ).rejects.toMatchObject({ reason: "request_failed" });
  expect(popup.close).toHaveBeenCalledTimes(2);
});
