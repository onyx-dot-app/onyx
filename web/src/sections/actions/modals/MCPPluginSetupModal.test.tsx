import { renderHook } from "@testing-library/react";
import useSWR from "swr";
import { PointerEventsCheckLevel } from "@testing-library/user-event";
import { ReadableStream } from "node:stream/web";
import {
  act,
  deferred,
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import * as UserProvider from "@/providers/UserProvider";
import { Permission } from "@/lib/types";
import { Tier } from "@/lib/tiers/types";
import {
  MCPServerStatus,
  MCPTransportType,
  type MCPSetupProbeResult,
} from "@/lib/mcp/types";
import MCPPluginSetupModal from "@/sections/actions/modals/MCPPluginSetupModal";
import messages from "@/i18n/messages/en.json";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";

const mockClose = jest.fn();
const mockCompleted = jest.fn();
const mockRouter = { push: jest.fn() };

function SetupModal() {
  return (
    <MCPPluginSetupModal open onClose={mockClose} onCompleted={mockCompleted} />
  );
}
jest.mock("next/navigation", () => ({
  ...jest.requireActual("next/navigation"),
  useRouter: () => mockRouter,
  usePathname: () => "/admin/plugins",
}));
jest.mock("@/providers/UserProvider", () => {
  const actual = jest.requireActual<typeof UserProvider>(
    "@/providers/UserProvider"
  );
  return { ...actual, useUser: jest.fn(actual.useUser) };
});

const publicResult: MCPSetupProbeResult = {
  kind: "public",
  transport: MCPTransportType.STREAMABLE_HTTP,
  server_name: "Analytics MCP",
  tool_count: 3,
};
const oauthResult: MCPSetupProbeResult = {
  kind: "oauth",
  transport: MCPTransportType.SSE,
  discovery: {
    status: "metadata_found",
    supports_automatic_registration: true,
    authorization_endpoint: "https://identity.example.com/authorize",
    token_endpoint: "https://identity.example.com/token",
  },
};
const copy = messages.actions.mcpSetup;
let probeResponse: (url: string) => Promise<MCPSetupProbeResult>;
let toolsFail: boolean;
let toolsResponse: Promise<Response> | null;
let oauthResponse: Promise<Response> | null;
let writes: { path: string; method?: string; body: unknown }[];
let probeUrls: string[];
let probeSignals: (AbortSignal | null | undefined)[];
let craftAvailable: boolean;
let defaultChatFails: boolean;

function authority(scoped = false, denied = false) {
  const base = renderHook(() =>
    jest
      .requireActual<typeof UserProvider>("@/providers/UserProvider")
      .useUser()
  );
  jest.mocked(UserProvider.useUser).mockReturnValue({
    ...base.result.current,
    userResolution: "resolved",
    permissions:
      scoped || denied
        ? []
        : [Permission.MANAGE_ACTIONS, Permission.FULL_ADMIN_PANEL_ACCESS],
    adminCapabilities: scoped ? [Permission.MANAGE_ACTIONS] : [],
  });
  base.unmount();
}

beforeEach(() => {
  mockClose.mockClear();
  mockCompleted.mockClear();
  authority();
  writes = [];
  probeUrls = [];
  probeSignals = [];
  toolsFail = false;
  toolsResponse = null;
  oauthResponse = null;
  craftAvailable = true;
  defaultChatFails = false;
  probeResponse = async () => publicResult;
  jest.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    const json = (value: unknown, status = 200) =>
      new Response(JSON.stringify(value), { status });
    if (path === "/api/settings")
      return json({
        tier: Tier.BUSINESS,
        ee_features_enabled: true,
        onyx_craft_available: craftAvailable,
      });
    if (path === "/api/enterprise-settings") return json({});
    if (path === "/api/manage/admin/user-group")
      return json([{ id: 1, name: "Engineering", users: [] }]);
    if (path === "/api/auth/type")
      return json({ auth_type: "basic", oauth_enabled: false });
    if (path === "/api/admin/mcp/probe/stream") {
      const payload: unknown = JSON.parse(String(init?.body));
      if (
        !payload ||
        typeof payload !== "object" ||
        !("server_url" in payload) ||
        typeof payload.server_url !== "string"
      )
        throw new Error("Invalid probe body");
      probeUrls.push(payload.server_url);
      probeSignals.push(init?.signal);
      const result = probeResponse(payload.server_url);
      const response = new Response(null);
      Object.defineProperty(response, "body", {
        value: new ReadableStream({
          async start(controller) {
            const send = (event: object) =>
              controller.enqueue(
                new TextEncoder().encode(JSON.stringify(event) + "\n")
              );
            send({
              type: "progress",
              stage: "contacting_server",
              state: "pending",
            });
            const value = await result;
            send({
              type: "progress",
              stage: "contacting_server",
              state: value.kind === "unreachable" ? "error" : "success",
            });
            if (value.kind !== "unreachable") {
              send({
                type: "progress",
                stage: "authentication",
                state: "pending",
              });
              send({
                type: "progress",
                stage: "authentication",
                state: value.kind === "auth_unknown" ? "error" : "success",
              });
            }
            send({ type: "result", result: value });
            controller.close();
          },
        }),
      });
      return response;
    }
    if (init?.method === "POST" || init?.method === "PATCH")
      writes.push({
        path,
        method: init.method,
        body: init.body ? JSON.parse(String(init.body)) : undefined,
      });
    if (
      path === "/api/admin/default-assistant" ||
      path === "/api/admin/default-assistant/configuration"
    )
      return defaultChatFails
        ? json({ detail: "Chat configuration unavailable" }, 503)
        : json({ tool_ids: [], available_tools: [] });
    if (path === "/api/admin/mcp/server" || path === "/api/admin/mcp/server/7")
      return json({
        id: 7,
        name: "Analytics MCP",
        server_url: "https://example.com/mcp",
        owner: "admin@example.com",
        status: MCPServerStatus.CREATED,
        is_public: true,
        groups: [],
        users: [],
        tool_count: 0,
      });
    if (path === "/api/admin/mcp/servers/create") return json({ server_id: 7 });
    if (path === "/api/admin/mcp/oauth/connect")
      return (
        oauthResponse ?? json({ status: "already_authenticated", server_id: 7 })
      );
    if (path === "/api/admin/mcp/servers") return json({ mcp_servers: [] });
    if (
      path === SWR_KEYS.mcpServers ||
      path === SWR_KEYS.mcpServersCraft ||
      path === SWR_KEYS.agentMcpServers(1)
    )
      return json({ mcp_servers: [] });
    if (path.includes("/status?")) return json({});
    if (path.includes("/tools/snapshots?source=mcp"))
      return (
        toolsResponse ??
        (toolsFail ? json({ detail: "Tool listing failed" }, 502) : json([]))
      );
    throw new Error(`Unexpected request ${path}`);
  });
});
afterEach(() => jest.restoreAllMocks());

async function enterUrl(url = "https://example.com/mcp") {
  const input = await screen.findByRole("textbox", { name: /^MCP Server URL/ });
  fireEvent.change(input, { target: { value: url } });
  return input;
}
async function openConnection() {
  await enterUrl();
  const next = screen.getByRole("button", { name: copy.continue });
  await waitFor(() => expect(next).toBeEnabled(), { timeout: 3000 });
  await setupUser().click(next);
  await screen.findByRole("combobox", {
    name: messages.actions.mcpAuthModal.authType.label,
  });
}
async function openDetails() {
  await openConnection();
}

test.each([true, false])(
  "first successful setup enables Chat and respects Craft availability: %s",
  async (available) => {
    craftAvailable = available;
    toolsResponse = Promise.resolve(new Response(JSON.stringify([{ id: 81 }])));
    render(<SetupModal />);
    await openConnection();
    await setupUser().click(screen.getByRole("button", { name: copy.connect }));
    await waitFor(() => expect(mockCompleted).toHaveBeenCalled());
    expect(
      writes.find((write) => write.path === "/api/admin/default-assistant")
        ?.body
    ).toEqual({ tool_ids: [81] });
    expect(
      writes.find((write) => write.path === "/api/admin/mcp/server")?.body
    ).toEqual(expect.objectContaining({ available_in_craft: available }));
  }
);

test("first OAuth setup carries the Chat enable intent and enables after already-authenticated discovery", async () => {
  probeResponse = async () => oauthResult;
  toolsResponse = Promise.resolve(new Response(JSON.stringify([{ id: 81 }])));
  render(<SetupModal />);
  await openConnection();
  await setupUser().click(screen.getByRole("button", { name: copy.connect }));
  await waitFor(() => expect(mockCompleted).toHaveBeenCalled());
  expect(
    writes.find((write) => write.path === "/api/admin/mcp/oauth/connect")?.body
  ).toEqual(
    expect.objectContaining({
      server_id: 7,
      return_path: "/admin/plugins/mcp/7?trigger_fetch=true&enable_chat=true",
    })
  );
  expect(
    writes.find((write) => write.path === "/api/admin/default-assistant")?.body
  ).toEqual({ tool_ids: [81] });
});

test("personal API-key setup keeps the admin's credential personal while enabling Chat", async () => {
  toolsResponse = Promise.resolve(new Response(JSON.stringify([{ id: 81 }])));
  render(<SetupModal />);
  await openConnection();
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  await user.click(
    screen.getByRole("combobox", {
      name: messages.actions.mcpAuthModal.authType.label,
    })
  );
  await user.click(await screen.findByRole("option", { name: "API Key" }));
  await user.type(
    screen.getByLabelText("API Key", { selector: "input" }),
    "personal-token"
  );
  await user.click(screen.getByRole("button", { name: copy.connect }));
  await waitFor(() => expect(mockCompleted).toHaveBeenCalled());
  expect(
    writes.find((write) => write.path === "/api/admin/mcp/servers/create")?.body
  ).toEqual(
    expect.objectContaining({
      auth_performer: "PER_USER",
      admin_credentials: { api_key: "personal-token" },
    })
  );
  expect(
    writes.find((write) => write.path === "/api/admin/default-assistant")?.body
  ).toEqual({ tool_ids: [81] });
});

test("a rejected Chat enable remains an actionable setup error, not success", async () => {
  toolsResponse = Promise.resolve(new Response(JSON.stringify([{ id: 81 }])));
  jest.spyOn(console, "error").mockImplementation(() => undefined);
  const fetchSetup = jest.mocked(global.fetch).getMockImplementation();
  jest.mocked(global.fetch).mockImplementation(async (input, init) => {
    if (
      String(input) === "/api/admin/default-assistant" &&
      init?.method === "PATCH"
    )
      return new Response(JSON.stringify({ detail: "Enable failed" }), {
        status: 503,
      });
    if (!fetchSetup) throw new Error("Missing setup network");
    return fetchSetup(input, init);
  });
  render(<SetupModal />);
  await openConnection();
  await setupUser().click(screen.getByRole("button", { name: copy.connect }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Enable failed");
  expect(mockCompleted).not.toHaveBeenCalled();
});

test("failed discovery never enables Chat or completes setup", async () => {
  toolsFail = true;
  jest.spyOn(console, "error").mockImplementation(() => undefined);
  render(<SetupModal />);
  await openConnection();
  await setupUser().click(screen.getByRole("button", { name: copy.connect }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Tool listing failed"
  );
  expect(
    writes.some((write) => write.path === "/api/admin/default-assistant")
  ).toBe(false);
  expect(mockCompleted).not.toHaveBeenCalled();
});

test("successful setup refreshes the current user's directory, Craft and composer caches", async () => {
  function MemberCacheObservers() {
    useSWR(SWR_KEYS.mcpServers, errorHandlingFetcher);
    useSWR(SWR_KEYS.mcpServersCraft, errorHandlingFetcher);
    useSWR(SWR_KEYS.agentMcpServers(1), errorHandlingFetcher);
    return null;
  }
  toolsResponse = Promise.resolve(new Response(JSON.stringify([{ id: 81 }])));
  render(
    <>
      <MemberCacheObservers />
      <SetupModal />
    </>
  );
  await openConnection();
  const readCount = (key: string) =>
    jest
      .mocked(global.fetch)
      .mock.calls.filter(([input]) => String(input) === key).length;
  for (const key of [
    SWR_KEYS.mcpServers,
    SWR_KEYS.mcpServersCraft,
    SWR_KEYS.agentMcpServers(1),
  ])
    expect(readCount(key)).toBe(1);
  await setupUser().click(screen.getByRole("button", { name: copy.connect }));
  await waitFor(() => expect(mockCompleted).toHaveBeenCalled());
  for (const key of [
    SWR_KEYS.mcpServers,
    SWR_KEYS.mcpServersCraft,
    SWR_KEYS.agentMcpServers(1),
  ])
    expect(readCount(key)).toBe(2);
});

test("Connect waits for the editable default Chat configuration before creating a server", async () => {
  const configuration = deferred<Response>();
  const fetchSetup = jest.mocked(global.fetch).getMockImplementation();
  jest.mocked(global.fetch).mockImplementation((input, init) => {
    if (String(input) === "/api/admin/default-assistant/configuration")
      return configuration.promise;
    if (!fetchSetup) throw new Error("Missing setup network");
    return fetchSetup(input, init);
  });
  toolsResponse = Promise.resolve(new Response(JSON.stringify([{ id: 81 }])));
  render(<SetupModal />);
  await openConnection();
  const connect = screen.getByRole("button", { name: copy.connect });
  expect(connect).toBeDisabled();
  expect(writes).toEqual([]);
  await act(async () => {
    configuration.resolve(
      new Response(JSON.stringify({ tool_ids: [], available_tools: [] }))
    );
  });
  await waitFor(() => expect(connect).toBeEnabled());
  await setupUser().click(connect);
  await waitFor(() => expect(mockCompleted).toHaveBeenCalled());
});

test.each([MCPTransportType.SSE, MCPTransportType.STREAMABLE_HTTP] as const)(
  "shows the translated detected transport label for %s",
  async (transport) => {
    probeResponse = async () => ({ ...publicResult, transport });
    render(<SetupModal />);
    await enterUrl();
    expect(
      await screen.findByText(
        transport === MCPTransportType.SSE
          ? messages.actions.mcpAuthModal.transport.sseLabel
          : messages.actions.mcpAuthModal.transport.httpLabel
      )
    ).toBeVisible();
  }
);

test("missing Chat configuration cannot silently complete first setup", async () => {
  defaultChatFails = true;
  toolsResponse = Promise.resolve(new Response(JSON.stringify([{ id: 81 }])));
  jest.spyOn(console, "error").mockImplementation(() => undefined);
  render(<SetupModal />);
  await openConnection();
  await setupUser().click(screen.getByRole("button", { name: copy.connect }));
  expect(await screen.findByRole("alert")).toBeVisible();
  expect(mockCompleted).not.toHaveBeenCalled();
  expect(
    writes.some((write) => write.path === "/api/admin/default-assistant")
  ).toBe(false);
});

test("starts with name and URL fields and shows detection before Continue without saving", async () => {
  const pending = deferred<MCPSetupProbeResult>();
  probeResponse = () => pending.promise;
  render(<SetupModal />);
  await enterUrl();
  expect(screen.getAllByRole("textbox")).toHaveLength(2);
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  await screen.findByRole("status", {}, { timeout: 3000 });
  expect(screen.getByText(copy.contactingServer)).toBeVisible();
  expect(screen.getByRole("button", { name: copy.continue })).toBeDisabled();
  expect(
    screen.getByText(copy.contactingServer).closest("[data-stage]")
  ).toHaveAttribute("data-state", "pending");
  expect(
    screen.getByText(copy.detectingAuthentication).closest("[data-stage]")
  ).toHaveAttribute("data-state", "waiting");
  await act(async () => pending.resolve(publicResult));
  expect(await screen.findByText(copy.publicDetected)).toBeVisible();
  expect(
    screen.getByText(copy.publicDetected).closest("[data-stage]")
  ).toHaveAttribute("data-state", "success");
  expect(
    screen
      .getByText(messages.actions.mcpAuthModal.transport.label)
      .closest("[data-stage]")
  ).toHaveAttribute("data-state", "success");
  expect(screen.getAllByRole("textbox")).toHaveLength(2);
  expect(writes).toEqual([]);
  await setupUser().click(screen.getByRole("button", { name: copy.continue }));
  expect(
    screen.queryByRole("textbox", { name: "Server Name" })
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("combobox", {
      name: messages.actions.mcpAuthModal.authType.label,
    })
  ).toHaveValue("No authentication");
  expect(
    screen.getByText(copy.connectTo.replace("{name}", "Analytics MCP"))
  ).toBeVisible();
  expect(writes).toEqual([]);
  await setupUser().click(screen.getByRole("button", { name: copy.back }));
  expect(screen.getByRole("textbox", { name: "Server Name" })).toHaveValue(
    "Analytics MCP"
  );
  expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  expect(writes).toEqual([]);
});

test("Cancel closes an empty setup modal", async () => {
  render(<SetupModal />);
  await screen.findByRole("textbox", { name: /^MCP Server URL/ });
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  await setupUser().click(screen.getByRole("button", { name: "Cancel" }));
  expect(mockClose).toHaveBeenCalled();
  expect(writes).toEqual([]);
});
test.each(["Cancel", "Escape", "backdrop", "Close"] as const)(
  "%s closes a dirty setup without confirmation or saving",
  async (action) => {
    render(<SetupModal />);
    await enterUrl();
    const user = setupUser();
    if (action === "Escape") await user.keyboard("{Escape}");
    else if (action === "backdrop")
      fireEvent.pointerDown(document.body, { pointerType: "mouse", button: 0 });
    else await user.click(screen.getByRole("button", { name: action }));
    await waitFor(() => expect(mockClose).toHaveBeenCalledTimes(1));
    expect(
      screen.queryByRole("button", {
        name: messages.chat.modals.unsavedChanges.discardButton.label,
      })
    ).not.toBeInTheDocument();
    expect(writes).toEqual([]);
  }
);

test("a closed modal performs no requests and reopening starts a fresh seeded draft", async () => {
  const view = render(
    <MCPPluginSetupModal
      open={false}
      onClose={mockClose}
      onCompleted={mockCompleted}
    />
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(global.fetch).not.toHaveBeenCalled();
  view.rerender(
    <MCPPluginSetupModal
      open
      onClose={mockClose}
      onCompleted={mockCompleted}
      initialUrl="https://example.com/mcp"
      initialName="Workspace analytics"
    />
  );
  expect(
    await screen.findByRole("textbox", { name: /^MCP Server URL/ })
  ).toHaveValue("https://example.com/mcp");
  await waitFor(
    () =>
      expect(screen.getByRole("button", { name: copy.continue })).toBeEnabled(),
    { timeout: 3000 }
  );
  expect(probeUrls).toEqual(["https://example.com/mcp"]);
  await setupUser().click(screen.getByRole("button", { name: copy.continue }));
  await setupUser().click(screen.getByRole("button", { name: copy.back }));
  expect(
    await screen.findByRole("textbox", { name: "Server Name" })
  ).toHaveValue("Workspace analytics");
  view.rerender(
    <MCPPluginSetupModal
      open={false}
      onClose={mockClose}
      onCompleted={mockCompleted}
    />
  );
  view.rerender(<SetupModal />);
  expect(
    await screen.findByRole("textbox", { name: /^MCP Server URL/ })
  ).toHaveValue("");
  expect(writes).toEqual([]);
});

test("closing the session aborts its pending probe", async () => {
  const pending = deferred<MCPSetupProbeResult>();
  probeResponse = () => pending.promise;
  const view = render(<SetupModal />);
  await enterUrl();
  await screen.findByRole("status", {}, { timeout: 3000 });
  expect(probeSignals).toHaveLength(1);
  view.rerender(
    <MCPPluginSetupModal
      open={false}
      onClose={mockClose}
      onCompleted={mockCompleted}
    />
  );
  expect(probeSignals[0]?.aborted).toBe(true);
  await act(async () => pending.resolve(publicResult));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(writes).toEqual([]);
});

test("busy Connect rejects dismissal until the request completes", async () => {
  const pending = deferred<Response>();
  toolsResponse = pending.promise;
  render(<SetupModal />);
  await openDetails();
  const user = setupUser();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: copy.connect })).toBeEnabled()
  );
  await user.click(screen.getByRole("button", { name: copy.connect }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled()
  );
  await user.keyboard("{Escape}");
  await user.click(screen.getByRole("button", { name: "Close" }));
  fireEvent.pointerDown(document.body, { pointerType: "mouse", button: 0 });
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  expect(mockClose).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("dialog", {
      name: messages.chat.modals.unsavedChanges.header.title,
    })
  ).not.toBeInTheDocument();
  await act(async () => pending.resolve(new Response("[]")));
  await waitFor(() =>
    expect(mockCompleted).toHaveBeenCalledWith(
      expect.objectContaining({ id: 7 })
    )
  );
});

test("OAuth saves and failures never add an unload guard", async () => {
  probeResponse = async () => oauthResult;
  const pending = deferred<Response>();
  oauthResponse = pending.promise;
  jest.spyOn(console, "error").mockImplementation(() => undefined);
  render(<SetupModal />);
  await openConnection();
  const user = setupUser();
  await user.click(
    screen.getByRole("radio", { name: "Use your own OAuth client" })
  );
  fireEvent.change(screen.getByRole("textbox", { name: /^Client ID/ }), {
    target: { value: "workspace-client" },
  });
  const dirtyUnload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(dirtyUnload);
  expect(dirtyUnload.defaultPrevented).toBe(false);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: copy.connect })).toBeEnabled()
  );
  await user.click(screen.getByRole("button", { name: copy.connect }));
  await waitFor(() =>
    expect(writes).toContainEqual(
      expect.objectContaining({ path: "/api/admin/mcp/oauth/connect" })
    )
  );
  const savedUnload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(savedUnload);
  expect(savedUnload.defaultPrevented).toBe(false);
  await act(async () =>
    pending.resolve(
      new Response(
        JSON.stringify({ detail: "Authorization could not start" }),
        { status: 502 }
      )
    )
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Authorization could not start"
  );
  const failedUnload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(failedUnload);
  expect(failedUnload.defaultPrevented).toBe(false);
  expect(mockCompleted).not.toHaveBeenCalled();
});

test("debounces URL edits and discards a stale probe", async () => {
  const stale = deferred<MCPSetupProbeResult>();
  probeResponse = (url) =>
    url.includes("first") ? stale.promise : Promise.resolve(oauthResult);
  render(<SetupModal />);
  const input = await enterUrl("https://first.example.com/mcp");
  await screen.findByRole("status", {}, { timeout: 3000 });
  fireEvent.change(input, {
    target: { value: "https://second.example.com/mcp" },
  });
  expect(
    await screen.findByText(copy.oauthDetected, {}, { timeout: 3000 })
  ).toBeVisible();
  await act(async () => stale.resolve(publicResult));
  expect(screen.queryByText(copy.publicDetected)).not.toBeInTheDocument();
  expect(probeUrls).toEqual([
    "https://first.example.com/mcp",
    "https://second.example.com/mcp",
  ]);
});

test("keeps a detected result when the URL changes only in whitespace", async () => {
  render(<SetupModal />);
  const input = await enterUrl();
  await screen.findByText(copy.publicDetected, {}, { timeout: 3000 });
  fireEvent.change(input, { target: { value: " https://example.com/mcp " } });
  expect(screen.getByRole("button", { name: copy.continue })).toBeEnabled();
  expect(probeUrls).toEqual(["https://example.com/mcp"]);
});

test("Back preserves connection credentials and final details without saving", async () => {
  probeResponse = async () => oauthResult;
  render(<SetupModal />);
  await openConnection();
  const user = setupUser();
  await user.click(
    screen.getByRole("radio", { name: "Use your own OAuth client" })
  );
  fireEvent.change(screen.getByRole("textbox", { name: /^Client ID/ }), {
    target: { value: "private-client" },
  });
  await user.click(screen.getByRole("button", { name: copy.back }));
  fireEvent.change(
    await screen.findByRole("textbox", { name: "Server Name" }),
    { target: { value: "Custom name" } }
  );
  expect(writes).toEqual([]);
  await user.click(screen.getByRole("button", { name: copy.continue }));
  expect(screen.getByRole("textbox", { name: /^Client ID/ })).toHaveValue(
    "private-client"
  );
  await user.click(screen.getByRole("button", { name: copy.back }));
  expect(screen.getByRole("textbox", { name: "Server Name" })).toHaveValue(
    "Custom name"
  );
  expect(writes).toEqual([]);
});

test("returning to the URL preserves credentials until the endpoint changes", async () => {
  probeResponse = async () => oauthResult;
  render(<SetupModal />);
  await openConnection();
  const user = setupUser();
  await user.click(
    screen.getByRole("radio", { name: "Use your own OAuth client" })
  );
  fireEvent.change(screen.getByRole("textbox", { name: /^Client ID/ }), {
    target: { value: "private-client" },
  });
  await user.click(screen.getByRole("button", { name: copy.back }));
  await waitFor(() =>
    expect(
      screen.getByRole("textbox", { name: /^MCP Server URL/ })
    ).toHaveFocus()
  );
  await user.click(screen.getByRole("button", { name: copy.continue }));
  expect(screen.getByRole("textbox", { name: /^Client ID/ })).toHaveValue(
    "private-client"
  );
  await user.click(screen.getByRole("button", { name: copy.back }));
  await enterUrl("https://different.example.com/mcp");
  await waitFor(
    () =>
      expect(screen.getByRole("button", { name: copy.continue })).toBeEnabled(),
    { timeout: 3000 }
  );
  await user.click(screen.getByRole("button", { name: copy.continue }));
  expect(
    screen.getByRole("radio", { name: "Set up automatically" })
  ).toHaveAttribute("aria-checked", "true");
  await user.click(
    screen.getByRole("radio", { name: "Use your own OAuth client" })
  );
  expect(screen.getByRole("textbox", { name: /^Client ID/ })).toHaveValue("");
  expect(writes).toEqual([]);
});

test("Back retains an explicit OAuth setup choice and a changed endpoint resets it", async () => {
  probeResponse = async () => ({
    kind: "oauth",
    transport: MCPTransportType.STREAMABLE_HTTP,
    discovery: {
      status: "metadata_found",
      supports_automatic_registration: false,
      authorization_endpoint: "https://identity.example.com/authorize",
      token_endpoint: "https://identity.example.com/token",
    },
  });
  render(<SetupModal />);
  await openConnection();
  const user = setupUser();
  await user.click(screen.getByRole("radio", { name: "Set up automatically" }));
  await user.click(screen.getByRole("button", { name: copy.back }));
  await user.click(screen.getByRole("button", { name: copy.continue }));
  expect(
    screen.getByRole("radio", { name: "Set up automatically" })
  ).toHaveAttribute("aria-checked", "true");
  await user.click(screen.getByRole("button", { name: copy.back }));
  await enterUrl("https://another.example.com/mcp");
  await waitFor(
    () =>
      expect(screen.getByRole("button", { name: copy.continue })).toBeEnabled(),
    { timeout: 3000 }
  );
  await user.click(screen.getByRole("button", { name: copy.continue }));
  expect(
    screen.getByRole("radio", { name: "Use your own OAuth client" })
  ).toHaveAttribute("aria-checked", "true");
  expect(writes).toEqual([]);
});

test("Connect creates a scoped server once and a failed tool retry updates the same server", async () => {
  authority(true);
  toolsFail = true;
  jest.spyOn(console, "error").mockImplementation(() => undefined);
  render(<SetupModal />);
  await openDetails();
  const user = setupUser();
  expect(
    screen.queryByRole("option", { name: /^Public/ })
  ).not.toBeInTheDocument();
  const connect = screen.getByRole("button", { name: copy.connect });
  expect(connect).toBeDisabled();
  const groups = screen.getByPlaceholderText("Add user groups");
  await user.click(groups);
  expect(groups).toHaveFocus();
  await screen.findByRole("option", { name: /^Engineering/ });
  await user.keyboard("{ArrowDown}{Enter}");
  await waitFor(() => expect(connect).toBeEnabled());
  await user.click(connect);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Tool listing failed"
  );
  expect(
    writes.find((write) => write.path === "/api/admin/mcp/server")?.body
  ).toEqual(
    expect.objectContaining({ is_public: false, groups: [1], users: [] })
  );
  await user.click(screen.getByRole("button", { name: copy.back }));
  const name = screen.getByRole("textbox", { name: "Server Name" });
  fireEvent.change(name, { target: { value: "Updated analytics" } });
  toolsFail = false;
  await user.click(screen.getByRole("button", { name: copy.continue }));
  await user.click(screen.getByRole("button", { name: copy.connect }));
  await waitFor(() =>
    expect(mockCompleted).toHaveBeenCalledWith(
      expect.objectContaining({ id: 7 })
    )
  );
  expect(
    writes.filter((write) => write.path === "/api/admin/mcp/server")
  ).toHaveLength(1);
  expect(
    writes.find((write) => write.path === "/api/admin/mcp/server/7")?.body
  ).toEqual(
    expect.objectContaining({
      name: "Updated analytics",
      is_public: false,
      groups: [1],
    })
  );
});

test.each(["blocked", "connection_failed"] as const)(
  "handles an unreachable endpoint without unsafe continuation: %s",
  async (reason) => {
    probeResponse = async () => ({ kind: "unreachable", reason });
    render(<SetupModal />);
    await enterUrl();
    await screen.findByRole("alert", {}, { timeout: 3000 });
    expect(screen.getByRole("button", { name: copy.continue })).toBeDisabled();
    if (reason === "blocked")
      expect(
        screen.queryByRole("button", { name: copy.configureManually })
      ).not.toBeInTheDocument();
    else {
      await setupUser().click(
        screen.getByRole("button", { name: copy.configureManually })
      );
      expect(
        await screen.getByRole("combobox", {
          name: messages.actions.mcpAuthModal.authType.label,
        })
      ).not.toHaveValue("No authentication");
      expect(
        screen.queryByRole("textbox", { name: "Server Name" })
      ).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: copy.connect })).toBeDisabled();
    }
    expect(writes).toEqual([]);
  }
);

test("denied users cannot probe or configure a server", async () => {
  authority(false, true);
  render(<SetupModal />);
  expect(await screen.findByText(copy.permissionDenied)).toBeVisible();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(probeUrls).toEqual([]);
  expect(writes).toEqual([]);
});

test.each([true, false, null])(
  "OAuth setup defaults follow confirmed registration support: %s",
  async (supported) => {
    probeResponse = async () => ({
      ...oauthResult,
      kind: "oauth",
      discovery: {
        status: "metadata_found",
        supports_automatic_registration: supported,
        authorization_endpoint: "https://identity.example.com/authorize",
        token_endpoint: "https://identity.example.com/token",
      },
    });
    render(<SetupModal />);
    await openConnection();
    expect(
      screen.getByRole("combobox", {
        name: messages.actions.mcpAuthModal.authType.label,
      })
    ).toHaveValue("OAuth");
    expect(
      screen.getByRole("radio", {
        name:
          supported === false
            ? "Use your own OAuth client"
            : "Set up automatically",
      })
    ).toHaveAttribute("aria-checked", "true");
    expect(writes).toEqual([]);
  }
);

test("unknown authentication needs an explicit choice before Connect can save", async () => {
  probeResponse = async () => ({ kind: "auth_unknown", transport: null });
  render(<SetupModal />);
  await openConnection();
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  const method = screen.getByRole("combobox", {
    name: messages.actions.mcpAuthModal.authType.label,
  });
  const connect = screen.getByRole("button", { name: copy.connect });
  expect(method).toHaveValue("");
  expect(connect).toBeDisabled();
  expect(writes).toEqual([]);
  await user.click(method);
  await user.click(screen.getByRole("option", { name: "No authentication" }));
  await waitFor(() => expect(connect).toBeEnabled());
  await user.click(connect);
  await waitFor(() =>
    expect(mockCompleted).toHaveBeenCalledWith(
      expect.objectContaining({ id: 7 })
    )
  );
  expect(
    writes.find((write) => write.path === "/api/admin/mcp/servers/create")?.body
  ).toEqual(expect.objectContaining({ auth_type: "NONE" }));
});

test("retry checks the same unreachable endpoint without creating a server", async () => {
  probeResponse = async () => ({
    kind: "unreachable",
    reason: "connection_failed",
  });
  render(<SetupModal />);
  await enterUrl();
  await screen.findByRole("alert", {}, { timeout: 3000 });
  probeResponse = async () => publicResult;
  await setupUser().click(screen.getByRole("button", { name: copy.retry }));
  await waitFor(
    () =>
      expect(screen.getByRole("button", { name: copy.continue })).toBeEnabled(),
    { timeout: 3000 }
  );
  expect(probeUrls).toEqual([
    "https://example.com/mcp",
    "https://example.com/mcp",
  ]);
  expect(writes).toEqual([]);
});

test("waits for resolved permissions before exposing setup or probing a seeded URL", async () => {
  const current = renderHook(() => UserProvider.useUser());
  const resolved = current.result.current;
  current.unmount();
  jest
    .mocked(UserProvider.useUser)
    .mockReturnValue({ ...resolved, userResolution: "loading" });
  const modal = (
    <MCPPluginSetupModal
      open
      initialUrl="https://example.com/mcp"
      onClose={mockClose}
      onCompleted={mockCompleted}
    />
  );
  const view = render(modal);
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(probeUrls).toEqual([]);
  jest.mocked(UserProvider.useUser).mockReturnValue(resolved);
  view.rerender(
    <MCPPluginSetupModal
      open
      initialUrl="https://example.com/mcp"
      onClose={mockClose}
      onCompleted={mockCompleted}
    />
  );
  expect(
    await screen.findByRole("textbox", { name: /^MCP Server URL/ })
  ).toHaveValue("https://example.com/mcp");
  await screen.findByText(copy.publicDetected, {}, { timeout: 3000 });
  expect(probeUrls).toEqual(["https://example.com/mcp"]);
  expect(writes).toEqual([]);
});

test("invalid manual OAuth JSON causes no writes and a corrected retry creates one server", async () => {
  probeResponse = async () => oauthResult;
  jest.spyOn(console, "error").mockImplementation(() => undefined);
  render(<SetupModal />);
  await openConnection();
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  const authCopy = messages.actions.mcpAuthModal;
  await user.click(
    screen.getByRole("radio", { name: authCopy.oauthSetup.ownClient.label })
  );
  fireEvent.change(screen.getByRole("textbox", { name: /^Client ID/ }), {
    target: { value: "manual-client" },
  });
  await user.click(
    screen.getByRole("combobox", { name: authCopy.providerMode.placeholder })
  );
  await user.click(
    screen.getByRole("option", {
      name: new RegExp(authCopy.providerMode.knownProvider.label),
    })
  );
  fireEvent.change(
    screen.getByRole("textbox", { name: authCopy.authorizationEndpoint.label }),
    {
      target: { value: "https://identity.example.com/authorize" },
    }
  );
  fireEvent.change(
    screen.getByRole("textbox", { name: authCopy.tokenEndpoint.label }),
    {
      target: { value: "https://identity.example.com/token" },
    }
  );
  const additional = screen.getByLabelText(
    authCopy.additionalAuthParams.label,
    { exact: false }
  );
  fireEvent.change(additional, { target: { value: "{invalid" } });
  const connect = screen.getByRole("button", { name: copy.connect });
  await waitFor(() => expect(connect).toBeEnabled());
  await user.click(connect);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Invalid additional auth params JSON"
  );
  expect(writes).toEqual([]);
  expect(additional).toHaveAttribute("aria-invalid", "true");
  fireEvent.change(additional, { target: { value: '{"prompt":"consent"}' } });
  await waitFor(() => expect(connect).toBeEnabled());
  await user.click(connect);
  await waitFor(() =>
    expect(mockCompleted).toHaveBeenCalledWith(
      expect.objectContaining({ id: 7 })
    )
  );
  expect(
    writes.filter((write) => write.path === "/api/admin/mcp/server")
  ).toHaveLength(1);
  expect(
    writes.filter((write) => write.path === "/api/admin/mcp/servers/create")
  ).toEqual([
    {
      path: "/api/admin/mcp/servers/create",
      method: "POST",
      body: expect.objectContaining({
        existing_server_id: 7,
        oauth_client_id: "manual-client",
        oauth_additional_auth_params: { prompt: "consent" },
      }),
    },
  ]);
});
