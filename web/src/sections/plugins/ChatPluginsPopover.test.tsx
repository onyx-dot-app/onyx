import { MCPConnectionStatus } from "@/lib/mcp/types";
import { ReadableStream } from "node:stream/web";
import { Button } from "@opal/components";
import {
  render,
  act,
  deferred,
  fireEvent,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import type { MinimalAgent } from "@/lib/agents/types";
import { sendMessage } from "@/app/app/services/lib";
import { enabledChatToolIds } from "@/lib/plugins/chat";
import { useToolConfiguration } from "@/lib/tools/hooks";
import ToolsPopover from "@/lib/tools/components/ToolsPopover";
import { ValidSources } from "@/lib/connectors/types/source";
import { MCPAuthenticationType } from "@/lib/mcp/types";
import {
  jsonResponse,
  memberServer,
  memberTool,
  storedMcpTool,
} from "@/sections/plugins/__tests__/memberPluginFixtures";
import messages from "@/i18n/messages/en.json";

const mockRouter = { push: jest.fn(), replace: jest.fn() };
let mockChatId: string | null = "chat-a";
let mockProjectId: number | null = null;
jest.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  usePathname: () => "/app",
  useSearchParams: () =>
    new URLSearchParams(
      mockChatId ? `chatId=${mockChatId}` : `projectId=${mockProjectId}`
    ),
}));
jest.mock("@/lib/position/hooks", () => ({
  useAppPosition: () => ({
    chat: () => mockChatId,
    agent: () => null,
    project: () => mockProjectId,
  }),
}));
jest.mock("@/lib/agents/hooks", () => ({
  useActiveAgent: () => ({ id: 5 }),
}));
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ vectorDbEnabled: true }),
}));
jest.mock("@/lib/projects/providers", () => ({
  useProjectsContext: () => ({
    currentProjectId: mockProjectId,
    allCurrentProjectFiles: [],
  }),
}));
jest.mock("@/hooks/useCCPairs", () => ({
  __esModule: true,
  default: () => ({ ccPairs: [{ id: 1 }] }),
}));
jest.mock("@/lib/connectors/hooks", () => ({
  useAvailableSources: () => ({
    availableSources: ["slack", "notion"],
    settled: true,
  }),
}));

const attachedTools = [
  memberTool({ id: 1, in_code_tool_id: "SearchTool", definition: null }),
  memberTool({
    id: 2,
    in_code_tool_id: "FileReaderTool",
    chat_selectable: false,
  }),
  storedMcpTool,
  memberTool({ id: 72, mcp_server_id: 7, definition: null }),
  memberTool(),
];
const agent: MinimalAgent = {
  id: 5,
  name: "Support agent",
  description: "Help support resolve tickets",
  tools: attachedTools,
  starter_messages: null,
  document_sets: [],
  is_public: true,
  is_listed: true,
  display_priority: null,
  is_featured: false,
  builtin_persona: false,
  owner: null,
  owner_group: null,
  user_permission: "VIEWER",
};

function PickerHarness({
  selectedAgent = agent,
}: {
  selectedAgent?: MinimalAgent;
}) {
  const configuration = useToolConfiguration();
  return (
    <>
      <ToolsPopover agent={selectedAgent} toolConfiguration={configuration} />
      <Button
        onClick={() =>
          void sendMessage({
            message: "Find support tickets",
            chatSessionId: mockChatId ?? "new-chat",
            parentMessageId: null,
            filters: null,
            forcedToolId: configuration.forcedToolId,
            enabledToolIds: enabledChatToolIds(
              selectedAgent.tools,
              configuration
            ),
          }).next()
        }
      >
        Send
      </Button>
    </>
  );
}

function network({
  credentials = false,
  credentialFailure = false,
  listFailure = false,
  privateAttachedServer = false,
  oauthFailure = false,
  oauthExpired = false,
} = {}) {
  let connected = !credentials;
  const requests: unknown[] = [];
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "/api/mcp/servers" && privateAttachedServer) {
        return jsonResponse({ mcp_servers: [] });
      }
      if (url === "/api/mcp/servers" || url === "/api/mcp/servers/persona/5") {
        if (listFailure) return jsonResponse({ detail: "Unavailable" }, 503);
        return jsonResponse({
          mcp_servers: [
            memberServer({
              is_public: !privateAttachedServer,
              default_chat_enabled: false,
              auth_type: credentials
                ? MCPAuthenticationType.API_TOKEN
                : MCPAuthenticationType.OAUTH,
              connection_status: connected
                ? MCPConnectionStatus.CONNECTED
                : MCPConnectionStatus.NOT_CONNECTED,
            }),
          ],
        });
      }
      if (url === "/api/tool")
        return jsonResponse([
          ...attachedTools.map((tool) =>
            tool.id === 7 && (oauthFailure || oauthExpired)
              ? { ...tool, oauth_config_id: 4 }
              : tool
          ),
          memberTool({
            id: 8,
            name: "Unavailable plugin",
            display_name: "Unavailable plugin",
          }),
        ]);
      if (url === "/api/user-oauth-token/status")
        return oauthFailure
          ? jsonResponse({ detail: "Unavailable" }, 503)
          : jsonResponse(
              oauthExpired
                ? [{ oauth_config_id: 4, expires_at: 1, is_expired: true }]
                : []
            );
      if (url === "/api/mcp/user-credentials") {
        if (credentialFailure)
          return jsonResponse({ detail: "Permission denied" }, 403);
        connected = true;
        return jsonResponse({});
      }
      if (url === "/api/chat/send-chat-message") {
        if (typeof init?.body !== "string")
          throw new Error("Missing JSON body");
        requests.push(JSON.parse(init.body));
        const response = new Response("", { status: 200 });
        Object.defineProperty(response, "body", {
          value: new ReadableStream({
            start(controller) {
              controller.close();
            },
          }),
        });
        return response;
      }
      throw new Error(`Unexpected request ${url}`);
    });
  return { requests, fetchSpy };
}

beforeEach(() => {
  sessionStorage.clear();
  mockChatId = "chat-a";
  mockProjectId = null;
});
afterEach(() => jest.restoreAllMocks());

async function openPlugins(user = setupUser()) {
  await user.click(
    within(screen.getByTestId("action-management-toggle")).getByRole("button")
  );
  await user.click(screen.getByRole("button", { name: "Plugins" }));
}

test("plugin-only agents reach a dedicated Plugins row through Actions", async () => {
  network();
  render(
    <PickerHarness selectedAgent={{ ...agent, tools: [storedMcpTool] }} />
  );
  expect(
    screen.queryByRole("button", { name: "Plugins" })
  ).not.toBeInTheDocument();
  await setupUser().click(
    within(screen.getByTestId("action-management-toggle")).getByRole("button")
  );
  expect(screen.getByRole("button", { name: "Plugins" })).toHaveAttribute(
    "aria-haspopup",
    "dialog"
  );
});

test("the Plugins flyout stays horizontal while toggling and searches its own roster", async () => {
  network();
  render(<PickerHarness />);
  const user = setupUser();
  await openPlugins(user);
  expect(
    screen.getByRole("dialog", { name: "Plugins" }).getAttribute("data-side")
  ).toMatch(/^(right|left)$/);
  expect(screen.getByRole("dialog", { name: "Plugins" })).toHaveAttribute(
    "data-align",
    "end"
  );
  const toggle = await screen.findByRole("switch", {
    name: "Use Linear in this chat",
  });
  await user.click(toggle);
  expect(toggle).not.toBeChecked();
  expect(screen.getByTestId("tool-options")).toBeVisible();
  await user.type(
    screen.getByRole("textbox", { name: "Search plugins" }),
    "Reports"
  );
  expect(
    screen.queryByRole("switch", { name: "Use Linear in this chat" })
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("switch", { name: "Use Reports API in this chat" })
  ).toBeVisible();
});

test("keyboard navigation returns from the flyout before dismissing Actions", async () => {
  network();
  render(<PickerHarness />);
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Manage Actions" }));
  const row = screen.getByRole("button", { name: "Plugins" });
  act(() => row.focus());
  await user.keyboard("{ArrowRight}");
  expect(screen.getByRole("textbox", { name: "Search plugins" })).toHaveFocus();
  await user.keyboard("{ArrowLeft}");
  expect(row).toHaveFocus();
  expect(
    screen.queryByRole("dialog", { name: "Plugins" })
  ).not.toBeInTheDocument();
  await user.keyboard("{ArrowRight}");
  await user.keyboard("{Escape}");
  expect(row).toHaveFocus();
  expect(screen.getByTestId("tool-options")).toBeVisible();
  await user.keyboard("{Escape}");
  expect(screen.queryByTestId("tool-options")).not.toBeInTheDocument();
});

test("delayed hover preserves the corridor from the Plugins row to its flyout", async () => {
  network();
  render(<PickerHarness />);
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Manage Actions" }));
  const row = screen.getByRole("button", { name: "Plugins" });
  await user.hover(row);
  const flyout = await screen.findByRole("dialog", { name: "Plugins" });
  await user.unhover(row);
  await user.hover(flyout);
  await act(async () => new Promise((resolve) => setTimeout(resolve, 300)));
  expect(flyout).toBeVisible();
  await user.unhover(flyout);
  await waitFor(() =>
    expect(
      screen.queryByRole("dialog", { name: "Plugins" })
    ).not.toBeInTheDocument()
  );
  expect(screen.getByTestId("tool-options")).toBeVisible();
});

test("touch opens Plugins and browsing closes both menus", async () => {
  network();
  render(<PickerHarness />);
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Manage Actions" }));
  const row = screen.getByRole("button", { name: "Plugins" });
  await user.pointer([
    { keys: "[TouchA>]", target: row },
    { keys: "[/TouchA]", target: row },
  ]);
  expect(screen.getByRole("dialog", { name: "Plugins" })).toBeVisible();
  fireEvent.click(screen.getByRole("link", { name: "Browse plugins" }));
  expect(
    screen.queryByRole("dialog", { name: "Plugins" })
  ).not.toBeInTheDocument();
  expect(screen.queryByTestId("tool-options")).not.toBeInTheDocument();
});

test("switching agents closes a pending connection without applying it to the next agent", async () => {
  const { fetchSpy } = network({ credentials: true });
  const fetchFixture = fetchSpy.getMockImplementation();
  if (!fetchFixture) throw new Error("Missing network fixture");
  const save = deferred<Response>();
  fetchSpy.mockImplementation((input, init) => {
    if (String(input) === "/api/mcp/user-credentials") return save.promise;
    if (String(input) === "/api/mcp/servers/persona/8")
      return Promise.resolve(jsonResponse({ mcp_servers: [] }));
    return fetchFixture(input, init);
  });
  sessionStorage.setItem(
    "onyx:tools:chat:chat-a",
    JSON.stringify({ 71: "disabled", 72: "disabled" })
  );
  const { rerender } = render(<PickerHarness />);
  const user = setupUser();
  await openPlugins(user);
  await user.click(await screen.findByRole("button", { name: "Connect" }));
  await user.type(screen.getByLabelText("api_key"), "personal-key");
  await user.click(screen.getByRole("button", { name: "Connect" }));
  expect(screen.getByRole("button", { name: "Connecting..." })).toBeDisabled();
  rerender(<PickerHarness selectedAgent={{ ...agent, id: 8, tools: [] }} />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await act(async () => save.resolve(jsonResponse({})));
  expect(
    JSON.parse(sessionStorage.getItem("onyx:tools:chat:chat-a") ?? "{}")
  ).toMatchObject({ tools: { 71: "disabled", 72: "disabled" } });
  await openPlugins(user);
  expect(
    await screen.findByText("No plugins are available in this chat.")
  ).toBeVisible();
});

test("an expired OpenAPI grant offers sign-in instead of a plugin toggle", async () => {
  network({ oauthExpired: true });
  render(<PickerHarness />);
  await openPlugins();
  expect(await screen.findByRole("button", { name: "Connect" })).toBeVisible();
  expect(
    screen.queryByRole("switch", { name: "Use Reports API in this chat" })
  ).not.toBeInTheDocument();
});

test("an MCP group toggle serializes every attached ID through the send service", async () => {
  const { requests } = network();
  render(<PickerHarness />);
  const user = setupUser();
  await openPlugins(user);
  const linear = await screen.findByRole("switch", {
    name: "Use Linear in this chat",
  });
  expect(linear).toBeChecked();
  expect(screen.queryByText("Connected")).not.toBeInTheDocument();
  expect(
    screen.getByRole("switch", { name: "Use Reports API in this chat" })
  ).toBeChecked();
  expect(screen.queryByText("Unavailable plugin")).not.toBeInTheDocument();
  await user.click(linear);
  await user.keyboard("{Escape}");
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() =>
    expect(requests[0]).toMatchObject({
      allowed_tool_ids: [1, 2, 7],
      forced_tool_id: null,
      chat_session_id: "chat-a",
    })
  );
});

test("an attached private MCP server stays visible and can be excluded from the send request", async () => {
  const { requests } = network({ privateAttachedServer: true });
  render(<PickerHarness />);
  const user = setupUser();
  await openPlugins(user);
  const linear = await screen.findByRole("switch", {
    name: "Use Linear in this chat",
  });
  expect(linear).toBeChecked();
  await user.click(linear);
  expect(linear).not.toBeChecked();
  await user.keyboard("{Escape}");
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() =>
    expect(requests[0]).toMatchObject({
      allowed_tool_ids: [1, 2, 7],
      forced_tool_id: null,
      chat_session_id: "chat-a",
    })
  );
});

test("an OAuth status failure allows disabling a selected plugin but blocks enabling it again", async () => {
  const { requests } = network({ oauthFailure: true });
  render(<PickerHarness />);
  const user = setupUser();
  await openPlugins(user);
  await screen.findByRole("alert");
  const reports = screen.getByRole("switch", {
    name: "Use Reports API in this chat",
  });
  expect(reports).toBeChecked();
  expect(reports).not.toHaveAttribute("aria-disabled");
  await user.click(reports);
  expect(reports).not.toBeChecked();
  expect(reports).toHaveAttribute("aria-disabled", "true");
  await user.click(reports);
  expect(reports).not.toBeChecked();
  await user.keyboard("{Escape}");
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() =>
    expect(requests[0]).toMatchObject({
      allowed_tool_ids: [1, 2, 71, 72],
      forced_tool_id: null,
      chat_session_id: "chat-a",
    })
  );
});

test("the shared connection dialog reconnects without replacing the chat page", async () => {
  const { fetchSpy } = network({ credentials: true });
  sessionStorage.setItem(
    "onyx:tools:chat:chat-a",
    JSON.stringify({ 71: "disabled", 72: "disabled" })
  );
  render(<PickerHarness />);
  const user = setupUser();
  await openPlugins(user);
  await screen.findByRole("button", { name: "Connect" });
  expect(screen.queryByText("Add your credentials")).not.toBeInTheDocument();
  expect(screen.queryByText("Connect your account")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("switch", { name: "Use Linear in this chat" })
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Connect" }));
  expect(screen.queryByTestId("tool-options")).not.toBeInTheDocument();
  expect(screen.getByRole("dialog")).toBeVisible();
  await user.type(screen.getByLabelText("api_key"), "member-test-key");
  await user.click(screen.getByRole("button", { name: "Connect" }));
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  );
  await openPlugins(user);
  expect(
    await screen.findByRole("switch", { name: "Use Linear in this chat" })
  ).toBeChecked();
  expect(fetchSpy).toHaveBeenCalledWith(
    "/api/mcp/user-credentials",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        server_id: 7,
        credentials: { api_key: "member-test-key" },
        transport: "STREAMABLE_HTTP",
      }),
    })
  );
  expect(mockRouter.push).not.toHaveBeenCalled();
});

test("connection failure stays in the dialog and preserves disabled selection", async () => {
  network({ credentials: true, credentialFailure: true });
  sessionStorage.setItem(
    "onyx:tools:chat:chat-a",
    JSON.stringify({ 71: "disabled", 72: "disabled" })
  );
  render(<PickerHarness />);
  const user = setupUser();
  await openPlugins(user);
  await screen.findByRole("button", { name: "Connect" });
  await user.click(screen.getByRole("button", { name: "Connect" }));
  await user.type(screen.getByLabelText("api_key"), "invalid-member-key");
  await user.click(screen.getByRole("button", { name: "Connect" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    messages.actions.memberPlugins.connection.errors.request_failed
  );
  expect(screen.getByRole("dialog")).toBeVisible();
  expect(
    JSON.parse(sessionStorage.getItem("onyx:tools:chat:chat-a") ?? "{}")
  ).toMatchObject({ tools: { 71: "disabled", 72: "disabled" } });
});

test("browse retains the current chat and a partial roster failure offers retry", async () => {
  network({ listFailure: true });
  render(<PickerHarness />);
  await openPlugins();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Some plugins could not load. Try again."
  );
  expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Browse plugins" })).toHaveAttribute(
    "href",
    "/app/plugins?returnTo=%2Fapp%3FchatId%3Dchat-a"
  );
  expect(
    screen.getByRole("switch", { name: "Use Reports API in this chat" })
  ).toBeChecked();
});

test("the empty agent shows a useful empty state and no workspace plugin toggles", async () => {
  network();
  render(<PickerHarness selectedAgent={{ ...agent, tools: [] }} />);
  await openPlugins();
  expect(
    await screen.findByText("No plugins are available in this chat.")
  ).toBeVisible();
  expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Browse plugins" })).toBeVisible();
});

test("Actions keeps built-in search and Sources while custom plugins appear only in Plugins", async () => {
  network();
  render(
    <PickerHarness
      selectedAgent={{
        ...agent,
        knowledge_sources: [ValidSources.Slack, ValidSources.Notion],
      }}
    />
  );
  const user = setupUser();
  await user.click(
    within(screen.getByTestId("action-management-toggle")).getByRole("button")
  );
  const search = await screen.findByRole("button", { name: /Internal Search/ });
  expect(screen.queryByText("Reports API")).not.toBeInTheDocument();
  expect(screen.queryByText("Linear")).not.toBeInTheDocument();
  await user.click(search);
  const notion = await screen.findByRole("switch", { name: "Toggle Notion" });
  expect(notion).toBeChecked();
  await user.click(notion);
  expect(notion).not.toBeChecked();
  await waitFor(() =>
    expect(
      JSON.parse(sessionStorage.getItem("onyx:tools:chat:chat-a") ?? "{}")
    ).toMatchObject({
      tools: { 1: "forced" },
      filters: { selectedSources: ["slack"] },
    })
  );
});
