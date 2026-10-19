import {
  act,
  deferred,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import MCPPluginDetailPage from "@/views/admin/PluginsPage/MCPPluginDetailPage";
import {
  MCPAuthenticationType,
  MCPServerStatus,
  type MCPServer,
} from "@/lib/mcp/types";
import { refreshMCPServerTools, updateMCPServerStatus } from "@/lib/mcp/svc";
import messages from "@/i18n/messages/en.json";
import type { ToolSnapshot } from "@/lib/tools/types";
import {
  mintMcpChatEnableIntent,
  consumeMcpChatEnableIntent,
} from "@/sections/actions/mcpChatEnableIntent";

let mockUserId = "admin-user";
jest.mock("@/providers/UserProvider", () => {
  const actual = jest.requireActual<typeof import("@/providers/UserProvider")>(
    "@/providers/UserProvider"
  );
  return {
    ...actual,
    useUser: () => ({ ...actual.useUser(), user: { id: mockUserId } }),
  };
});

function json(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), init);
}

let mockFullAdmin = true;
const mockUpdateTools = jest.fn();
jest.mock("@/lib/agents/hooks", () => ({
  useDefaultAssistantConfiguration: () => ({
    canEdit: mockFullAdmin,
    data: { tool_ids: [] },
    isLoading: false,
    updateTools: mockUpdateTools,
  }),
}));
const mockPush = jest.fn();
const mockReplace = jest.fn();
const mockRouter = { push: mockPush, replace: mockReplace };
const onClose = jest.fn();
let openParams = new URLSearchParams();
jest.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  usePathname: () => "/admin/plugins",
}));
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({
    isGlobalHolder: mockFullAdmin,
    isScopedManager: false,
  }),
}));
jest.mock("@/lib/mcp/svc", () => ({
  updateMCPServer: jest.fn(),
  refreshMCPServerTools: jest.fn(),
  updateMCPServerStatus: jest.fn(),
  deleteMCPServer: jest.fn(),
}));
jest.mock(
  "@/views/admin/PluginsPage/components/mcp/MCPServerDetailsPage",
  () => ({
    __esModule: true,
    default: function MockDetails({
      server,
      onSaved,
      readOnly,
    }: {
      server: MCPServer;
      readOnly?: boolean;
      onSaved: (server: MCPServer) => Promise<void>;
    }) {
      return (
        <div>
          <input
            disabled={readOnly}
            aria-label="Server draft"
            defaultValue={server.name}
          />
          <button disabled={readOnly} onClick={() => void onSaved(server)}>
            Save server draft
          </button>
        </div>
      );
    },
  })
);
jest.mock(
  "@/views/admin/PluginsPage/components/mcp/MCPAuthenticationPage",
  () => ({
    __esModule: true,
    default: function MockAuth({
      onTriggerFetchTools,
      onComplete,
    }: {
      onTriggerFetchTools: (serverId: number) => Promise<void>;
      onComplete: () => void;
    }) {
      return (
        <div>
          <input aria-label="Authentication draft" />
          <button
            onClick={async () => {
              try {
                await onTriggerFetchTools(7);
                onComplete();
              } catch {}
            }}
          >
            Authenticate server
          </button>
        </div>
      );
    },
  })
);
jest.mock("@/sections/actions/MCPServerToolsEditor", () => ({
  __esModule: true,
  default: function MockTools() {
    return <button>Draft tool change</button>;
  },
}));
const server: MCPServer = {
  connection_status: null,
  id: 7,
  name: "Example MCP",
  server_url: "https://example.com/mcp",
  owner: "admin",
  auth_type: MCPAuthenticationType.NONE,
  status: MCPServerStatus.CONNECTED,
  is_public: true,
  groups: [],
  users: [],
  available_in_craft: true,
  tool_count: 3,
  permissions: { edit: true },
};
const discoveredTool: ToolSnapshot = {
  id: 81,
  name: "search",
  display_name: "Search",
  description: "Search records",
  definition: null,
  custom_headers: [],
  in_code_tool_id: null,
  passthrough_auth: false,
  enabled: true,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: false,
};

beforeEach(() => {
  sessionStorage.clear();
  mockUserId = "admin-user";
  jest.clearAllMocks();
  mockFullAdmin = true;
  openParams = new URLSearchParams();
  mockUpdateTools.mockResolvedValue(undefined);
  jest.mocked(refreshMCPServerTools).mockResolvedValue([]);
  jest.mocked(updateMCPServerStatus).mockResolvedValue();
  jest.spyOn(global, "fetch").mockImplementation(async () => json(server));
});
afterEach(() => jest.restoreAllMocks());

async function expectToolsTab() {
  await waitFor(() =>
    expect(
      screen.getByRole("tab", { name: messages.actions.mcpTools.title })
    ).toHaveAttribute("aria-selected", "true")
  );
}

test("keeps lifecycle controls on the Plugins directory, not detail", async () => {
  render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  await screen.findByRole("textbox", { name: "Server draft" });
  expect(
    screen.queryByRole("button", {
      name: /^(Enable|Disable) for workspace$|^Manage workspace availability$/,
    })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Enable" })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Delete" })
  ).not.toBeInTheDocument();
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  expect(screen.getByRole("dialog")).toHaveAccessibleDescription(
    server.server_url
  );
});

test("offers read-only details when edit permission is absent", async () => {
  mockFullAdmin = false;
  const fetchWithFixtures = jest.mocked(global.fetch).getMockImplementation();
  jest
    .mocked(global.fetch)
    .mockImplementation(async (input, init) =>
      String(input) === "/api/admin/mcp/servers/7"
        ? json({ ...server, permissions: {} })
        : fetchWithFixtures
          ? fetchWithFixtures(input, init)
          : json({})
    );
  render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  await screen.findByRole("textbox", { name: "Server draft" });
  expect(
    screen.queryByRole("switch", {
      name: messages.actions.addMcpModal.defaultChat.title,
    })
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", {
      name: "Save server draft",
    })
  ).toBeDisabled();
  expect(
    screen.queryByRole("button", {
      name: "Authentication draft",
    })
  ).not.toBeInTheDocument();
});

test("renders not-found feedback without retry for an absent server", async () => {
  jest
    .mocked(global.fetch)
    .mockImplementation(async () =>
      json({ detail: "Not found" }, { status: 404 })
    );
  render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  expect(
    await screen.findByText(messages.actions.mcpDetail.notFound)
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: messages.actions.mcpDetail.retry })
  ).not.toBeInTheDocument();
});

test("rejects an invalid route ID without making a server request", async () => {
  render(<MCPPluginDetailPage serverId={NaN} onClose={onClose} />);
  expect(screen.getByText(messages.actions.mcpDetail.notFound)).toBeVisible();
  expect(
    jest
      .mocked(global.fetch)
      .mock.calls.some(([url]) => String(url).includes("/mcp/"))
  ).toBe(false);
});

test("closes the detail modal through onClose without routing", async () => {
  render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  await screen.findByRole("textbox", { name: "Server draft" });
  expect(screen.getByRole("dialog")).toBeVisible();
  await setupUser().click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).toHaveBeenCalled();
  expect(mockReplace).not.toHaveBeenCalled();
  expect(mockPush).not.toHaveBeenCalled();
});

test("closes without a discard prompt when server settings contain a draft", async () => {
  render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  const user = setupUser();
  await user.type(
    await screen.findByRole("textbox", { name: "Server draft" }),
    " edited"
  );
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).toHaveBeenCalled();
  expect(mockReplace).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("dialog", {
      name: messages.chat.modals.unsavedChanges.header.title,
    })
  ).not.toBeInTheDocument();
});

test("loads tools once after OAuth return and opens the Tools tab", async () => {
  openParams = new URLSearchParams(
    "trigger_fetch=true&message=oauth_connected&filter=one&filter=two"
  );
  const { rerender } = render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  await waitFor(() => expect(refreshMCPServerTools).toHaveBeenCalledWith(7));
  rerender(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  await expectToolsTab();
  expect(refreshMCPServerTools).toHaveBeenCalledTimes(1);
  expect(mockReplace).not.toHaveBeenCalled();
  expect(mockUpdateTools).not.toHaveBeenCalled();
});

test("query flags alone cannot enable discovered tools for main Chat", async () => {
  openParams = new URLSearchParams("trigger_fetch=true&enable_chat=true");
  jest.mocked(refreshMCPServerTools).mockResolvedValue([discoveredTool]);
  render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  await waitFor(() => expect(refreshMCPServerTools).toHaveBeenCalledWith(7));
  expect(mockUpdateTools).not.toHaveBeenCalled();
});

test("consumes an explicit Enable proof once after same-tab OAuth return", async () => {
  const token = mintMcpChatEnableIntent({ userId: mockUserId, serverId: 7 });
  openParams = new URLSearchParams(
    `trigger_fetch=true&enable_chat=true&enable_chat_intent=${token}`
  );
  jest.mocked(refreshMCPServerTools).mockResolvedValue([discoveredTool]);
  const view = render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  await waitFor(() => expect(mockUpdateTools).toHaveBeenCalledWith([81], true));
  expect(
    consumeMcpChatEnableIntent(token, { userId: mockUserId, serverId: 7 })
  ).toBe(false);
  await expectToolsTab();
  view.unmount();
  render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  await waitFor(() => expect(refreshMCPServerTools).toHaveBeenCalledTimes(2));
  expect(mockUpdateTools).toHaveBeenCalledTimes(1);
});

test("keeps the enable request after OAuth-return discovery fails", async () => {
  const token = mintMcpChatEnableIntent({ userId: mockUserId, serverId: 7 });
  openParams = new URLSearchParams(
    `trigger_fetch=true&enable_chat=true&enable_chat_intent=${token}`
  );
  jest
    .mocked(refreshMCPServerTools)
    .mockRejectedValueOnce(new Error("Unauthenticated"));
  render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  await waitFor(() => expect(refreshMCPServerTools).toHaveBeenCalledTimes(1));
  expect(mockUpdateTools).not.toHaveBeenCalled();
  await expectToolsTab();
  expect(
    consumeMcpChatEnableIntent(token, { userId: mockUserId, serverId: 7 })
  ).toBe(true);
});

test.each(["wrong user", "wrong server", "expired"])(
  "rejects %s proof on OAuth return",
  async (kind) => {
    const token = mintMcpChatEnableIntent({
      userId: kind === "wrong user" ? "another-user" : mockUserId,
      serverId: kind === "wrong server" ? 8 : 7,
    });
    if (kind === "expired")
      jest.spyOn(Date, "now").mockReturnValue(Date.now() + 300_000);
    openParams = new URLSearchParams(
      `trigger_fetch=true&enable_chat=true&enable_chat_intent=${token}`
    );
    jest.mocked(refreshMCPServerTools).mockResolvedValue([discoveredTool]);
    render(
      <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
    );
    await waitFor(() => expect(refreshMCPServerTools).toHaveBeenCalledWith(7));
    expect(mockUpdateTools).not.toHaveBeenCalled();
  }
);

test("does not apply a previous user's intent after an account change during discovery", async () => {
  const token = mintMcpChatEnableIntent({ userId: mockUserId, serverId: 7 });
  openParams = new URLSearchParams(
    `trigger_fetch=true&enable_chat_intent=${token}`
  );
  const discovery = deferred<ToolSnapshot[]>();
  jest.mocked(refreshMCPServerTools).mockReturnValue(discovery.promise);
  const view = render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  await waitFor(() => expect(refreshMCPServerTools).toHaveBeenCalledWith(7));
  mockUserId = "another-user";
  view.rerender(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  await act(async () => discovery.resolve([discoveredTool]));
  expect(mockUpdateTools).not.toHaveBeenCalled();
});

test("enables discovered tools after in-place authentication succeeds", async () => {
  const token = mintMcpChatEnableIntent({ userId: mockUserId, serverId: 7 });
  openParams = new URLSearchParams(
    `tab=authentication&enable_chat=true&enable_chat_intent=${token}`
  );
  jest.mocked(refreshMCPServerTools).mockResolvedValue([discoveredTool]);
  const user = setupUser();
  render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  await user.click(
    await screen.findByRole("button", { name: "Authenticate server" })
  );
  await waitFor(() => expect(mockUpdateTools).toHaveBeenCalledWith([81], true));
  await expectToolsTab();
});

test("keeps the enable request for a retry after the Chat update fails", async () => {
  const token = mintMcpChatEnableIntent({ userId: mockUserId, serverId: 7 });
  openParams = new URLSearchParams(
    `tab=authentication&enable_chat=true&enable_chat_intent=${token}`
  );
  jest.mocked(refreshMCPServerTools).mockResolvedValue([discoveredTool]);
  mockUpdateTools.mockRejectedValueOnce(new Error("Update failed"));
  const user = setupUser();
  render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  const authenticate = await screen.findByRole("button", {
    name: "Authenticate server",
  });
  await user.click(authenticate);
  await waitFor(() => expect(mockUpdateTools).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(authenticate).toBeEnabled());
  await user.click(authenticate);
  await waitFor(() => expect(mockUpdateTools).toHaveBeenCalledTimes(2));
  expect(
    consumeMcpChatEnableIntent(token, { userId: mockUserId, serverId: 7 })
  ).toBe(false);
});

test("does not enable tools when opening authentication is cancelled", async () => {
  const token = mintMcpChatEnableIntent({ userId: mockUserId, serverId: 7 });
  openParams = new URLSearchParams(
    `tab=authentication&enable_chat=true&enable_chat_intent=${token}`
  );
  const user = setupUser();
  render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  await screen.findByRole("textbox", { name: "Authentication draft" });
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).toHaveBeenCalled();
  expect(mockReplace).not.toHaveBeenCalled();
  expect(refreshMCPServerTools).not.toHaveBeenCalled();
  expect(mockUpdateTools).not.toHaveBeenCalled();
  expect(
    consumeMcpChatEnableIntent(token, { userId: mockUserId, serverId: 7 })
  ).toBe(false);
});

test("ordinary authentication does not enable main Chat", async () => {
  openParams = new URLSearchParams("tab=authentication");
  jest.mocked(refreshMCPServerTools).mockResolvedValue([discoveredTool]);
  const user = setupUser();
  render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  await user.click(
    await screen.findByRole("button", { name: "Authenticate server" })
  );
  await expectToolsTab();
  expect(mockUpdateTools).not.toHaveBeenCalled();
});

test("keeps the enable request for a retry after authentication discovery fails", async () => {
  const token = mintMcpChatEnableIntent({ userId: mockUserId, serverId: 7 });
  openParams = new URLSearchParams(
    `tab=authentication&enable_chat=true&enable_chat_intent=${token}`
  );
  jest
    .mocked(refreshMCPServerTools)
    .mockRejectedValueOnce(new Error("Unauthenticated"))
    .mockResolvedValue([discoveredTool]);
  const user = setupUser();
  render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  const authenticate = await screen.findByRole("button", {
    name: "Authenticate server",
  });
  await user.click(authenticate);
  await waitFor(() => expect(refreshMCPServerTools).toHaveBeenCalledTimes(1));
  expect(mockUpdateTools).not.toHaveBeenCalled();
  await waitFor(() => expect(authenticate).toBeEnabled());
  await user.click(authenticate);
  await waitFor(() => expect(mockUpdateTools).toHaveBeenCalledWith([81], true));
  expect(
    consumeMcpChatEnableIntent(token, { userId: mockUserId, serverId: 7 })
  ).toBe(false);
});

test("ignores forged enable intent without full admin authority", async () => {
  mockFullAdmin = false;
  openParams = new URLSearchParams("trigger_fetch=true&enable_chat=true");
  jest.mocked(refreshMCPServerTools).mockResolvedValue([discoveredTool]);
  render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  await waitFor(() => expect(refreshMCPServerTools).toHaveBeenCalled());
  expect(mockUpdateTools).not.toHaveBeenCalled();
});

test("opens on the tab from its parameters and selects tabs without URL writes", async () => {
  openParams = new URLSearchParams(
    "tab=authentication&message=oauth_connected"
  );
  const user = setupUser();
  render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  const authentication = await screen.findByRole("tab", {
    name: messages.actions.mcpDetail.authentication,
  });
  expect(authentication).toHaveAttribute("aria-selected", "true");
  await user.click(
    screen.getByRole("tab", { name: messages.actions.mcpDetail.configuration })
  );
  expect(
    screen.getByRole("tab", { name: messages.actions.mcpDetail.configuration })
  ).toHaveAttribute("aria-selected", "true");
  expect(mockReplace).not.toHaveBeenCalled();
  expect(mockPush).not.toHaveBeenCalled();
});

test("opens on the server tab without parameters", async () => {
  render(<MCPPluginDetailPage serverId={7} onClose={onClose} />);
  expect(
    await screen.findByRole("tab", {
      name: messages.actions.mcpDetail.configuration,
    })
  ).toHaveAttribute("aria-selected", "true");
  expect(refreshMCPServerTools).not.toHaveBeenCalled();
});

test("blocks editing and tool controls throughout OAuth discovery", async () => {
  openParams = new URLSearchParams("trigger_fetch=true");
  let finishStatus = () => {};
  let finishDiscovery = () => {};
  jest.mocked(updateMCPServerStatus).mockImplementation(
    () =>
      new Promise<void>((resolve) => {
        finishStatus = resolve;
      })
  );
  jest.mocked(refreshMCPServerTools).mockImplementation(
    () =>
      new Promise((resolve) => {
        finishDiscovery = () => resolve([]);
      })
  );
  render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  const edit = await screen.findByRole("tab", {
    name: messages.actions.mcpDetail.configuration,
  });
  await waitFor(() => expect(edit).toBeDisabled());
  const toolControl = screen.getByRole("button", { name: "Draft tool change" });
  expect(toolControl).toBeDisabled();
  finishStatus();
  await waitFor(() => expect(refreshMCPServerTools).toHaveBeenCalledTimes(1));
  expect(edit).toBeDisabled();
  expect(toolControl).toBeDisabled();
  finishDiscovery();
  await waitFor(() => expect(edit).toBeEnabled());
  expect(toolControl).toBeEnabled();
});

test("server edit permission alone cannot change default Chat settings", async () => {
  mockFullAdmin = false;
  render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  await screen.findByRole("textbox", { name: "Server draft" });
  expect(
    screen.queryByRole("switch", {
      name: messages.actions.addMcpModal.defaultChat.title,
    })
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", {
      name: "Save server draft",
    })
  ).toBeEnabled();
  expect(
    jest
      .mocked(global.fetch)
      .mock.calls.some(([url]) => String(url).includes("default-assistant"))
  ).toBe(false);
});

test("retains server and authentication drafts across inline tabs", async () => {
  render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  const user = setupUser();
  const name = await screen.findByRole("textbox", { name: "Server draft" });
  await user.type(name, " changed");
  await user.click(
    screen.getByRole("tab", { name: messages.actions.mcpDetail.authentication })
  );
  const credential = await screen.findByRole("textbox", {
    name: "Authentication draft",
  });
  await user.type(credential, "secret draft");
  await user.click(
    screen.getByRole("tab", { name: messages.actions.mcpDetail.configuration })
  );
  expect(screen.getByRole("textbox", { name: "Server draft" })).toHaveValue(
    "Example MCP changed"
  );
  await user.click(
    screen.getByRole("tab", { name: messages.actions.mcpDetail.authentication })
  );
  expect(
    screen.getByRole("textbox", { name: "Authentication draft" })
  ).toHaveValue("secret draft");
});

test("saving server configuration keeps the editor open", async () => {
  render(
    <MCPPluginDetailPage serverId={7} params={openParams} onClose={onClose} />
  );
  const user = setupUser();
  await user.type(
    await screen.findByRole("textbox", { name: "Server draft" }),
    " changed"
  );
  await user.click(screen.getByRole("button", { name: "Save server draft" }));
  await waitFor(() =>
    expect(screen.getByRole("textbox", { name: "Server draft" })).toBeVisible()
  );
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).toHaveBeenCalled();
  expect(mockReplace).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("dialog", {
      name: messages.chat.modals.unsavedChanges.header.title,
    })
  ).not.toBeInTheDocument();
  expect(mockPush).not.toHaveBeenCalled();
});
