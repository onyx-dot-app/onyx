import {
  act,
  deferred,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import MCPServerDetailPage from "@/sections/actions/MCPServerDetailPage";
import {
  MCPAuthenticationType,
  MCPServerStatus,
  type MCPServer,
  type MCPServerUpdateRequest,
} from "@/lib/mcp/types";
import { refreshMCPServerTools, updateMCPServerStatus } from "@/lib/mcp/svc";
import messages from "@/i18n/messages/en.json";
import type { ToolSnapshot } from "@/lib/tools/types";
import {
  mintMcpChatEnableIntent,
  consumeMcpChatEnableIntent,
} from "@/sections/actions/mcpChatEnableIntent";

let mockUserId = "admin-user";
let mockSavedServer: MCPServer | undefined;
const mockAuthenticate = jest.fn<Promise<MCPServer>, []>();
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
let mockSearchParams = new URLSearchParams();
jest.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  usePathname: () => "/admin/plugins/mcp/7",
  useSearchParams: () => mockSearchParams,
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
jest.mock("@/sections/actions/modals/MCPServerDetailsPage", () => ({
  __esModule: true,
  default: function MockDetails({
    server,
    onDirtyChange,
    onValuesChange,
    onSaved,
    onAuthenticate,
    readOnly,
  }: {
    server: MCPServer;
    readOnly?: boolean;
    onDirtyChange: (dirty: boolean) => void;
    onSaved: (server: MCPServer) => Promise<void>;
    onAuthenticate: (draft: MCPServerUpdateRequest) => void;
    onValuesChange?: () => void;
  }) {
    return (
      <div>
        <input
          disabled={readOnly}
          aria-label="Server draft"
          defaultValue={server.name}
          onChange={() => {
            onDirtyChange(true);
            onValuesChange?.();
          }}
        />
        <button
          onClick={() => {
            onDirtyChange(false);
            onValuesChange?.();
          }}
        >
          Revert configuration
        </button>
        <button
          disabled={readOnly}
          onClick={() => {
            onDirtyChange(false);
            void onSaved(mockSavedServer ?? server);
          }}
        >
          Save server draft
        </button>
        <button
          onClick={() => {
            onDirtyChange(true);
            onAuthenticate({
              server_url: "https://new.example.com/mcp",
              name: "Draft MCP",
            });
          }}
        >
          Stage URL draft
        </button>
      </div>
    );
  },
}));
jest.mock("@/sections/actions/modals/MCPAuthenticationPage", () => ({
  __esModule: true,
  default: function MockAuth({
    mcpServer,
    onDirtyChange,
    onSaved,
    configurationDraft,
    onAuthorize,
    onComplete,
  }: {
    mcpServer: MCPServer;
    onDirtyChange: (dirty: boolean) => void;
    onSaved: (server: MCPServer) => Promise<void>;
    configurationDraft?: MCPServerUpdateRequest;
    onAuthorize?: (url: string) => void;
    onComplete: () => void;
  }) {
    return (
      <div>
        <input
          aria-label="Authentication draft"
          data-server-url={mcpServer.server_url}
          data-auth-headers={JSON.stringify(mcpServer.auth_template?.headers)}
          data-configuration-name={configurationDraft?.name}
          data-server-status={mcpServer.status}
          data-has-credentials={!!mcpServer.admin_credentials}
          onChange={() => onDirtyChange(true)}
        />
        <button onClick={() => onAuthorize?.(window.location.href)}>
          Continue OAuth
        </button>
        <button
          onClick={async () => {
            try {
              const saved = await mockAuthenticate();
              await onSaved(saved);
              onComplete();
            } catch {}
          }}
        >
          Authenticate server
        </button>
      </div>
    );
  },
}));
jest.mock("@/sections/actions/MCPServerToolsEditor", () => ({
  __esModule: true,
  default: function MockTools({
    onDirtyChange,
  }: {
    onDirtyChange: (dirty: boolean) => void;
  }) {
    return (
      <button onClick={() => onDirtyChange(true)}>Draft tool change</button>
    );
  },
}));
const server: MCPServer = {
  connection_status: null,
  id: 7,
  name: "Example MCP",
  description: "Manage workspace projects.",
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
  mockSavedServer = undefined;
  jest.clearAllMocks();
  mockFullAdmin = true;
  mockSearchParams = new URLSearchParams();
  mockUpdateTools.mockResolvedValue(undefined);
  mockAuthenticate.mockResolvedValue(server);
  jest.mocked(refreshMCPServerTools).mockResolvedValue([]);
  jest.mocked(updateMCPServerStatus).mockResolvedValue();
  jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) =>
      String(input).includes("/tools/snapshots") ? json([]) : json(server)
    );
});
afterEach(() => jest.restoreAllMocks());

test("shows configuration without a lifecycle menu", async () => {
  render(<MCPServerDetailPage serverId={7} />);
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
    server.description
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
  render(<MCPServerDetailPage serverId={7} />);
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
  render(<MCPServerDetailPage serverId={7} />);
  expect(
    await screen.findByText(messages.actions.mcpDetail.notFound)
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: messages.actions.mcpDetail.retry })
  ).not.toBeInTheDocument();
});

test("rejects an invalid route ID without making a server request", async () => {
  render(<MCPServerDetailPage serverId={NaN} />);
  expect(screen.getByText(messages.actions.mcpDetail.notFound)).toBeVisible();
  expect(
    jest
      .mocked(global.fetch)
      .mock.calls.some(([url]) => String(url).includes("/mcp/"))
  ).toBe(false);
});

test("closes the detail modal to the directory without adding a history entry", async () => {
  render(<MCPServerDetailPage serverId={7} />);
  await screen.findByRole("textbox", { name: "Server draft" });
  expect(screen.getByRole("dialog")).toBeVisible();
  await setupUser().click(screen.getByRole("button", { name: "Close" }));
  expect(mockReplace).toHaveBeenCalledWith("/admin/plugins");
  expect(mockPush).not.toHaveBeenCalled();
});

test("guards modal close when server settings contain a draft", async () => {
  render(<MCPServerDetailPage serverId={7} />);
  const user = setupUser();
  await user.type(
    await screen.findByRole("textbox", { name: "Server draft" }),
    " edited"
  );
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(mockReplace).not.toHaveBeenCalled();
  await user.click(
    screen.getByRole("button", {
      name: messages.chat.modals.unsavedChanges.cancelButton.label,
    })
  );
  expect(screen.getByRole("textbox", { name: "Server draft" })).toHaveValue(
    "Example MCP edited"
  );
});

test("guards modal close for tool drafts and allows canceling discard", async () => {
  render(<MCPServerDetailPage serverId={7} />);
  const user = setupUser();
  await user.click(
    await screen.findByRole("tab", {
      name: messages.actions.mcpTools.title,
    })
  );
  await user.click(
    await screen.findByRole("button", { name: "Draft tool change" })
  );
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(await screen.findByRole("dialog")).toBeVisible();
  await user.click(
    screen.getByRole("button", {
      name: messages.chat.modals.unsavedChanges.cancelButton.label,
    })
  );
  expect(
    screen.queryByRole("dialog", {
      name: messages.chat.modals.unsavedChanges.header.title,
    })
  ).not.toBeInTheDocument();
  expect(mockPush).not.toHaveBeenCalled();
});

test("completed setup opens Tools without repeating discovery", async () => {
  mockSearchParams = new URLSearchParams("tab=tools");
  render(<MCPServerDetailPage serverId={7} />);
  expect(
    await screen.findByRole("tab", { name: messages.actions.mcpTools.title })
  ).toHaveAttribute("aria-selected", "true");
  expect(
    screen.getByRole("button", { name: "Draft tool change" })
  ).toBeVisible();
  expect(
    screen.queryByRole("textbox", { name: "Server draft" })
  ).not.toBeInTheDocument();
  expect(refreshMCPServerTools).not.toHaveBeenCalled();
});

test("loads tools once after OAuth return and preserves other query values", async () => {
  mockSearchParams = new URLSearchParams(
    "trigger_fetch=true&message=oauth_connected&filter=one&filter=two"
  );
  const { rerender } = render(<MCPServerDetailPage serverId={7} />);
  await waitFor(() => expect(refreshMCPServerTools).toHaveBeenCalledWith(7));
  rerender(<MCPServerDetailPage serverId={7} />);
  await waitFor(() =>
    expect(mockReplace).toHaveBeenCalledWith(
      "/admin/plugins/mcp/7?message=oauth_connected&filter=one&filter=two&tab=tools",
      { scroll: false }
    )
  );
  expect(refreshMCPServerTools).toHaveBeenCalledTimes(1);
  expect(
    screen.getByRole("tab", { name: messages.actions.mcpTools.title })
  ).toHaveAttribute("aria-selected", "true");
  expect(mockUpdateTools).not.toHaveBeenCalled();
});

test("query flags alone cannot enable discovered tools for main Chat", async () => {
  mockSearchParams = new URLSearchParams("trigger_fetch=true&enable_chat=true");
  jest.mocked(refreshMCPServerTools).mockResolvedValue([discoveredTool]);
  render(<MCPServerDetailPage serverId={7} />);
  await waitFor(() => expect(refreshMCPServerTools).toHaveBeenCalledWith(7));
  expect(mockUpdateTools).not.toHaveBeenCalled();
});

test("consumes an explicit Enable proof once after same-tab OAuth return", async () => {
  const token = mintMcpChatEnableIntent({ userId: mockUserId, serverId: 7 });
  mockSearchParams = new URLSearchParams(
    `trigger_fetch=true&enable_chat=true&enable_chat_intent=${token}`
  );
  jest.mocked(refreshMCPServerTools).mockResolvedValue([discoveredTool]);
  const view = render(<MCPServerDetailPage serverId={7} />);
  await waitFor(() => expect(mockUpdateTools).toHaveBeenCalledWith([81], true));
  expect(
    consumeMcpChatEnableIntent(token, { userId: mockUserId, serverId: 7 })
  ).toBe(false);
  expect(mockReplace).toHaveBeenLastCalledWith(
    "/admin/plugins/mcp/7?tab=tools",
    { scroll: false }
  );
  view.unmount();
  render(<MCPServerDetailPage serverId={7} />);
  await waitFor(() => expect(refreshMCPServerTools).toHaveBeenCalledTimes(2));
  expect(mockUpdateTools).toHaveBeenCalledTimes(1);
});

test("keeps the enable request after OAuth-return discovery fails", async () => {
  const token = mintMcpChatEnableIntent({ userId: mockUserId, serverId: 7 });
  mockSearchParams = new URLSearchParams(
    `trigger_fetch=true&enable_chat=true&enable_chat_intent=${token}`
  );
  jest
    .mocked(refreshMCPServerTools)
    .mockRejectedValueOnce(new Error("Unauthenticated"));
  render(<MCPServerDetailPage serverId={7} />);
  await waitFor(() => expect(refreshMCPServerTools).toHaveBeenCalledTimes(1));
  expect(mockUpdateTools).not.toHaveBeenCalled();
  expect(mockReplace).toHaveBeenLastCalledWith(
    `/admin/plugins/mcp/7?enable_chat=true&enable_chat_intent=${token}&tab=tools`,
    { scroll: false }
  );
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
    mockSearchParams = new URLSearchParams(
      `trigger_fetch=true&enable_chat=true&enable_chat_intent=${token}`
    );
    jest.mocked(refreshMCPServerTools).mockResolvedValue([discoveredTool]);
    render(<MCPServerDetailPage serverId={7} />);
    await waitFor(() => expect(refreshMCPServerTools).toHaveBeenCalledWith(7));
    expect(mockUpdateTools).not.toHaveBeenCalled();
  }
);

test("does not apply a previous user's intent after an account change during discovery", async () => {
  const token = mintMcpChatEnableIntent({ userId: mockUserId, serverId: 7 });
  mockSearchParams = new URLSearchParams(
    `trigger_fetch=true&enable_chat_intent=${token}`
  );
  const discovery = deferred<ToolSnapshot[]>();
  jest.mocked(refreshMCPServerTools).mockReturnValue(discovery.promise);
  const view = render(<MCPServerDetailPage serverId={7} />);
  await waitFor(() => expect(refreshMCPServerTools).toHaveBeenCalledWith(7));
  mockUserId = "another-user";
  view.rerender(<MCPServerDetailPage serverId={7} />);
  await act(async () => discovery.resolve([discoveredTool]));
  expect(mockUpdateTools).not.toHaveBeenCalled();
});

test("uses the staged result without another discovery or Chat write", async () => {
  const token = mintMcpChatEnableIntent({ userId: mockUserId, serverId: 7 });
  mockSearchParams = new URLSearchParams(
    `tab=authentication&enable_chat=true&enable_chat_intent=${token}`
  );
  const user = setupUser();
  render(<MCPServerDetailPage serverId={7} />);
  await user.click(
    await screen.findByRole("button", { name: "Authenticate server" })
  );
  await waitFor(() =>
    expect(mockReplace).toHaveBeenLastCalledWith(
      "/admin/plugins/mcp/7?tab=tools",
      { scroll: false }
    )
  );
  expect(refreshMCPServerTools).not.toHaveBeenCalled();
  expect(mockUpdateTools).not.toHaveBeenCalled();
  expect(
    consumeMcpChatEnableIntent(token, { userId: mockUserId, serverId: 7 })
  ).toBe(false);
});

test("does not enable tools when opening authentication is cancelled", async () => {
  const token = mintMcpChatEnableIntent({ userId: mockUserId, serverId: 7 });
  mockSearchParams = new URLSearchParams(
    `tab=authentication&enable_chat=true&enable_chat_intent=${token}`
  );
  const user = setupUser();
  render(<MCPServerDetailPage serverId={7} />);
  await screen.findByRole("textbox", { name: "Authentication draft" });
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(mockReplace).toHaveBeenCalledWith("/admin/plugins");
  expect(refreshMCPServerTools).not.toHaveBeenCalled();
  expect(mockUpdateTools).not.toHaveBeenCalled();
  expect(
    consumeMcpChatEnableIntent(token, { userId: mockUserId, serverId: 7 })
  ).toBe(false);
});

test("ordinary authentication does not enable main Chat", async () => {
  mockSearchParams = new URLSearchParams("tab=authentication");
  jest.mocked(refreshMCPServerTools).mockResolvedValue([discoveredTool]);
  const user = setupUser();
  render(<MCPServerDetailPage serverId={7} />);
  await user.click(
    await screen.findByRole("button", { name: "Authenticate server" })
  );
  await waitFor(() => expect(mockReplace).toHaveBeenCalled());
  expect(mockUpdateTools).not.toHaveBeenCalled();
});

test("authentication without a URL change preserves unrelated configuration drafts", async () => {
  const user = setupUser();
  render(<MCPServerDetailPage serverId={7} />);
  const draft = await screen.findByRole("textbox", { name: "Server draft" });
  await user.clear(draft);
  await user.type(draft, "Unsaved name");
  await user.click(
    screen.getByRole("tab", {
      name: messages.actions.mcpDetail.authentication,
    })
  );
  await user.click(screen.getByRole("button", { name: "Authenticate server" }));
  await waitFor(() =>
    expect(
      screen.getByRole("tab", { name: messages.actions.mcpTools.title })
    ).toHaveAttribute("aria-selected", "true")
  );
  await user.click(
    screen.getByRole("tab", { name: messages.actions.mcpDetail.configuration })
  );
  expect(screen.getByRole("textbox", { name: "Server draft" })).toHaveValue(
    "Unsaved name"
  );
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(
    screen.getByRole("dialog", {
      name: messages.chat.modals.unsavedChanges.header.title,
    })
  ).toBeVisible();
});

test("saving configuration with the original URL clears an older URL proposal", async () => {
  const user = setupUser();
  render(<MCPServerDetailPage serverId={7} />);
  await user.click(
    await screen.findByRole("button", { name: "Stage URL draft" })
  );
  await user.click(
    screen.getByRole("tab", { name: messages.actions.mcpDetail.configuration })
  );
  await user.click(screen.getByRole("button", { name: "Save server draft" }));
  await user.click(
    screen.getByRole("tab", {
      name: messages.actions.mcpDetail.authentication,
    })
  );
  const auth = screen.getByRole("textbox", { name: "Authentication draft" });
  expect(auth).toHaveAttribute("data-server-url", server.server_url);
  expect(auth).not.toHaveAttribute("data-configuration-name");
});

test("keeps staged URL and metadata after failure and clears them on success", async () => {
  const user = setupUser();
  render(<MCPServerDetailPage serverId={7} />);
  await user.click(
    await screen.findByRole("button", { name: "Stage URL draft" })
  );
  const auth = await screen.findByRole("textbox", {
    name: "Authentication draft",
  });
  expect(auth).toHaveAttribute(
    "data-server-url",
    "https://new.example.com/mcp"
  );
  expect(auth).toHaveAttribute("data-configuration-name", "Draft MCP");
  expect(auth).toHaveAttribute("data-has-credentials", "false");
  mockAuthenticate.mockRejectedValueOnce(new Error("Discovery failed"));
  await user.click(screen.getByRole("button", { name: "Authenticate server" }));
  expect(auth).toHaveAttribute("data-configuration-name", "Draft MCP");
  expect(screen.getByRole("dialog", { name: /^Example MCP/ })).toBeVisible();
  mockAuthenticate.mockResolvedValueOnce({
    ...server,
    name: "Draft MCP",
    server_url: "https://new.example.com/mcp",
  });
  await user.click(screen.getByRole("button", { name: "Authenticate server" }));
  await waitFor(() =>
    expect(
      screen.getByRole("tab", { name: messages.actions.mcpTools.title })
    ).toHaveAttribute("aria-selected", "true")
  );
  await user.click(
    screen.getByRole("tab", {
      name: messages.actions.mcpDetail.authentication,
    })
  );
  expect(
    screen.getByRole("textbox", { name: "Authentication draft" })
  ).not.toHaveAttribute("data-configuration-name");
  expect(refreshMCPServerTools).not.toHaveBeenCalled();
});

test("ignores forged enable intent without full admin authority", async () => {
  mockFullAdmin = false;
  mockSearchParams = new URLSearchParams("trigger_fetch=true&enable_chat=true");
  jest.mocked(refreshMCPServerTools).mockResolvedValue([discoveredTool]);
  render(<MCPServerDetailPage serverId={7} />);
  await waitFor(() => expect(refreshMCPServerTools).toHaveBeenCalled());
  expect(mockUpdateTools).not.toHaveBeenCalled();
});

test("preserves unrelated query values when selecting a tab", async () => {
  mockSearchParams = new URLSearchParams(
    "tab=server&message=oauth_connected&filter=one&filter=two"
  );
  const user = setupUser();
  render(<MCPServerDetailPage serverId={7} />);
  await user.click(
    await screen.findByRole("tab", {
      name: messages.actions.mcpDetail.authentication,
    })
  );
  expect(mockReplace).toHaveBeenCalledWith(
    "/admin/plugins/mcp/7?tab=authentication&message=oauth_connected&filter=one&filter=two",
    { scroll: false }
  );
});

test("blocks editing and tool controls throughout OAuth discovery", async () => {
  mockSearchParams = new URLSearchParams("trigger_fetch=true");
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
  render(<MCPServerDetailPage serverId={7} />);
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
  render(<MCPServerDetailPage serverId={7} />);
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
  render(<MCPServerDetailPage serverId={7} />);
  const user = setupUser();
  const name = await screen.findByRole("textbox", { name: "Server draft" });
  await user.type(name, " changed");
  await user.click(
    screen.getByRole("tab", {
      name: messages.actions.mcpDetail.authentication,
    })
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
    screen.getByRole("tab", {
      name: messages.actions.mcpDetail.authentication,
    })
  );
  expect(
    screen.getByRole("textbox", { name: "Authentication draft" })
  ).toHaveValue("secret draft");
  expect(
    screen.queryByRole("dialog", {
      name: messages.chat.modals.unsavedChanges.header.title,
    })
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(await screen.findByRole("dialog")).toBeVisible();
});

test("saving server configuration keeps the editor open and clears its draft guard", async () => {
  render(<MCPServerDetailPage serverId={7} />);
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
  expect(mockReplace).toHaveBeenCalledWith("/admin/plugins");
  expect(
    screen.queryByRole("dialog", {
      name: messages.chat.modals.unsavedChanges.header.title,
    })
  ).not.toBeInTheDocument();
  expect(mockPush).not.toHaveBeenCalled();
});

test("uses returned endpoint and cleared credentials when reload after URL save fails", async () => {
  const user = setupUser();
  jest
    .mocked(global.fetch)
    .mockResolvedValue(
      json({ ...server, admin_credentials: { api_key: "old-token" } })
    );
  render(<MCPServerDetailPage serverId={7} />);
  await screen.findByRole("textbox", { name: "Server draft" });
  mockSavedServer = {
    ...server,
    server_url: "https://new.example.com/mcp",
    status: MCPServerStatus.AWAITING_AUTH,
    admin_credentials: undefined,
  };
  jest.mocked(global.fetch).mockImplementation(async () => {
    throw new Error("Reload unavailable");
  });
  await user.click(screen.getByRole("button", { name: "Save server draft" }));
  await user.click(
    screen.getByRole("tab", {
      name: messages.actions.mcpDetail.authentication,
    })
  );
  const auth = await screen.findByRole("textbox", {
    name: "Authentication draft",
  });
  expect(auth).toHaveAttribute(
    "data-server-url",
    "https://new.example.com/mcp"
  );
  expect(auth).toHaveAttribute(
    "data-server-status",
    MCPServerStatus.AWAITING_AUTH
  );
  expect(auth).toHaveAttribute("data-has-credentials", "false");
});

test("reverting configuration without saving clears the staged URL", async () => {
  const user = setupUser();
  render(<MCPServerDetailPage serverId={7} />);
  await user.click(
    await screen.findByRole("button", { name: "Stage URL draft" })
  );
  await user.click(
    screen.getByRole("tab", { name: messages.actions.mcpDetail.configuration })
  );
  await user.click(
    screen.getByRole("button", { name: "Revert configuration" })
  );
  await user.click(
    screen.getByRole("tab", {
      name: messages.actions.mcpDetail.authentication,
    })
  );
  expect(
    screen.getByRole("textbox", { name: "Authentication draft" })
  ).toHaveAttribute("data-server-url", server.server_url);
});

test("URL changes require reentry of header literals even when they contain placeholders", async () => {
  jest.mocked(global.fetch).mockImplementation(async () =>
    json({
      ...server,
      auth_template: {
        headers: { Authorization: "Bearer old-secret-{user_email}" },
        required_fields: [],
      },
    })
  );
  const user = setupUser();
  render(<MCPServerDetailPage serverId={7} />);
  await user.click(
    await screen.findByRole("button", { name: "Stage URL draft" })
  );
  expect(
    screen.getByRole("textbox", { name: "Authentication draft" })
  ).toHaveAttribute("data-auth-headers", JSON.stringify({ Authorization: "" }));
});
test("intentional OAuth continuation removes the unsaved draft unload warning", async () => {
  const user = setupUser();
  render(<MCPServerDetailPage serverId={7} />);
  await user.click(
    await screen.findByRole("button", { name: "Stage URL draft" })
  );
  const before = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(before);
  expect(before.defaultPrevented).toBe(true);
  await user.click(screen.getByRole("button", { name: "Continue OAuth" }));
  const after = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(after);
  expect(after.defaultPrevented).toBe(false);
});

test("editing Configuration after staging invalidates the older proposal", async () => {
  const user = setupUser();
  render(<MCPServerDetailPage serverId={7} />);
  await user.click(
    await screen.findByRole("button", { name: "Stage URL draft" })
  );
  await user.click(
    screen.getByRole("tab", { name: messages.actions.mcpDetail.configuration })
  );
  await user.type(
    screen.getByRole("textbox", { name: "Server draft" }),
    " newer"
  );
  await user.click(
    screen.getByRole("tab", { name: messages.actions.mcpDetail.authentication })
  );
  expect(
    screen.getByRole("textbox", { name: "Authentication draft" })
  ).not.toHaveAttribute("data-configuration-name");
  await user.click(screen.getByRole("button", { name: "Authenticate server" }));
  await user.click(
    screen.getByRole("tab", { name: messages.actions.mcpDetail.configuration })
  );
  expect(screen.getByRole("textbox", { name: "Server draft" })).toHaveValue(
    server.name + " newer"
  );
});

test("URL authentication preserves an existing tool draft and its close guard", async () => {
  const user = setupUser();
  render(<MCPServerDetailPage serverId={7} />);
  await user.click(
    await screen.findByRole("button", { name: "Stage URL draft" })
  );
  await user.click(
    screen.getByRole("tab", { name: messages.actions.mcpTools.title })
  );
  const draft = screen.getByRole("button", { name: "Draft tool change" });
  await user.click(draft);
  await user.click(
    screen.getByRole("tab", { name: messages.actions.mcpDetail.authentication })
  );
  mockAuthenticate.mockResolvedValueOnce({
    ...server,
    server_url: "https://new.example.com/mcp",
  });
  await user.click(screen.getByRole("button", { name: "Authenticate server" }));
  await waitFor(() =>
    expect(
      screen.getByRole("tab", { name: messages.actions.mcpTools.title })
    ).toHaveAttribute("aria-selected", "true")
  );
  expect(screen.getByRole("button", { name: "Draft tool change" })).toBe(draft);
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(
    screen.getByRole("button", {
      name: messages.chat.modals.unsavedChanges.cancelButton.label,
    })
  ).toBeVisible();
});
