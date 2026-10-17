import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import MCPServerDetailPage from "@/sections/actions/MCPServerDetailPage";
import {
  MCPAuthenticationType,
  MCPServerStatus,
  type MCPServer,
} from "@/lib/mcp/types";
import { refreshMCPServerTools, updateMCPServerStatus } from "@/lib/mcp/svc";
import messages from "@/i18n/messages/en.json";
import type { ToolSnapshot } from "@/lib/tools/types";

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
    onSaved,
    readOnly,
  }: {
    server: MCPServer;
    readOnly?: boolean;
    onDirtyChange: (dirty: boolean) => void;
    onSaved: (server: MCPServer) => Promise<void>;
  }) {
    return (
      <div>
        <input
          disabled={readOnly}
          aria-label="Server draft"
          defaultValue={server.name}
          onChange={() => onDirtyChange(true)}
        />
        <button
          disabled={readOnly}
          onClick={() => {
            onDirtyChange(false);
            void onSaved(server);
          }}
        >
          Save server draft
        </button>
      </div>
    );
  },
}));
jest.mock("@/sections/actions/modals/MCPAuthenticationPage", () => ({
  __esModule: true,
  default: function MockAuth({
    onDirtyChange,
    onTriggerFetchTools,
    onComplete,
  }: {
    onDirtyChange: (dirty: boolean) => void;
    onTriggerFetchTools: (serverId: number) => Promise<void>;
    onComplete: () => void;
  }) {
    return (
      <div>
        <input
          aria-label="Authentication draft"
          onChange={() => onDirtyChange(true)}
        />
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
  jest.clearAllMocks();
  mockFullAdmin = true;
  mockSearchParams = new URLSearchParams();
  mockUpdateTools.mockResolvedValue(undefined);
  jest.mocked(refreshMCPServerTools).mockResolvedValue([]);
  jest.mocked(updateMCPServerStatus).mockResolvedValue();
  jest.spyOn(global, "fetch").mockImplementation(async () => json(server));
});
afterEach(() => jest.restoreAllMocks());

test("keeps lifecycle controls on the Plugins directory, not detail", async () => {
  render(<MCPServerDetailPage serverId={7} />);
  await screen.findByRole("textbox", { name: "Server draft" });
  expect(
    screen.queryByRole("button", { name: "Enable or disable for workspace" })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Enable" })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Delete" })
  ).not.toBeInTheDocument();
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
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
  expect(mockUpdateTools).not.toHaveBeenCalled();
});

test("enables discovered tools after an explicit Enable OAuth return and consumes the intent", async () => {
  mockSearchParams = new URLSearchParams("trigger_fetch=true&enable_chat=true");
  jest.mocked(refreshMCPServerTools).mockResolvedValue([discoveredTool]);
  render(<MCPServerDetailPage serverId={7} />);
  await waitFor(() => expect(mockUpdateTools).toHaveBeenCalledWith([81], true));
  await waitFor(() =>
    expect(mockReplace).toHaveBeenLastCalledWith(
      "/admin/plugins/mcp/7?tab=tools",
      { scroll: false }
    )
  );
  expect(mockUpdateTools).toHaveBeenCalledTimes(1);
});

test("enables discovered tools after in-place authentication succeeds", async () => {
  mockSearchParams = new URLSearchParams("tab=authentication&enable_chat=true");
  jest.mocked(refreshMCPServerTools).mockResolvedValue([discoveredTool]);
  const user = setupUser();
  render(<MCPServerDetailPage serverId={7} />);
  await user.click(
    await screen.findByRole("button", { name: "Authenticate server" })
  );
  await waitFor(() => expect(mockUpdateTools).toHaveBeenCalledWith([81], true));
  expect(mockReplace).toHaveBeenLastCalledWith(
    "/admin/plugins/mcp/7?tab=tools",
    { scroll: false }
  );
});

test("does not enable tools when opening authentication is cancelled", async () => {
  mockSearchParams = new URLSearchParams("tab=authentication&enable_chat=true");
  const user = setupUser();
  render(<MCPServerDetailPage serverId={7} />);
  await screen.findByRole("textbox", { name: "Authentication draft" });
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(mockReplace).toHaveBeenCalledWith("/admin/plugins");
  expect(refreshMCPServerTools).not.toHaveBeenCalled();
  expect(mockUpdateTools).not.toHaveBeenCalled();
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

test("does not enable tools when authentication discovery fails", async () => {
  mockSearchParams = new URLSearchParams("tab=authentication&enable_chat=true");
  jest
    .mocked(refreshMCPServerTools)
    .mockRejectedValue(new Error("Unauthenticated"));
  const user = setupUser();
  render(<MCPServerDetailPage serverId={7} />);
  await user.click(
    await screen.findByRole("button", { name: "Authenticate server" })
  );
  await waitFor(() => expect(refreshMCPServerTools).toHaveBeenCalled());
  expect(mockUpdateTools).not.toHaveBeenCalled();
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
