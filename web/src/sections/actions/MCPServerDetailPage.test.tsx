import type { ReactNode } from "react";
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import MCPServerDetailPage from "@/sections/actions/MCPServerDetailPage";
import {
  MCPAuthenticationType,
  MCPServerStatus,
  type MCPServer,
} from "@/lib/mcp/types";
import {
  updateMCPServer,
  refreshMCPServerTools,
  updateMCPServerStatus,
} from "@/lib/mcp/svc";
import { useSettings } from "@/lib/settings/hooks";
import messages from "@/i18n/messages/en.json";

function json(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), init);
}

let mockFullAdmin = true;
let mockToolIds = [1, 2, 99];
let mockDefaultSaveFails = false;
const mockDefaultWrites: number[][] = [];
const mockPush = jest.fn();
const mockReplace = jest.fn();
const mockRouter = { push: mockPush, replace: mockReplace };
let mockSearchParams = new URLSearchParams();
jest.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  usePathname: () => "/admin/mcp-actions/7",
  useSearchParams: () => mockSearchParams,
}));
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({
    isGlobalHolder: mockFullAdmin,
    isScopedManager: false,
  }),
}));
jest.mock("@/lib/settings/hooks", () => ({ useSettings: jest.fn() }));
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
    afterFields,
    readOnly,
  }: {
    server: MCPServer;
    afterFields?: ReactNode;
    readOnly?: boolean;
    onDirtyChange: (dirty: boolean) => void;
    onSaved: (server: MCPServer, advance: boolean) => Promise<void>;
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
            void onSaved(server, false);
          }}
        >
          Save server draft
        </button>
        {afterFields}
      </div>
    );
  },
}));
jest.mock("@/sections/actions/modals/MCPAuthenticationPage", () => ({
  __esModule: true,
  default: function MockAuth({
    onDirtyChange,
  }: {
    onDirtyChange: (dirty: boolean) => void;
  }) {
    return (
      <input
        aria-label="Authentication draft"
        onChange={() => onDirtyChange(true)}
      />
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

beforeEach(() => {
  jest.clearAllMocks();
  mockFullAdmin = true;
  mockToolIds = [1, 2, 99];
  mockDefaultSaveFails = false;
  mockDefaultWrites.length = 0;
  mockSearchParams = new URLSearchParams();
  jest
    .mocked(useSettings)
    .mockReturnValue({ onyx_craft_available: true } as ReturnType<
      typeof useSettings
    >);
  jest.mocked(updateMCPServer).mockResolvedValue(server);
  jest.mocked(refreshMCPServerTools).mockResolvedValue([]);
  jest.mocked(updateMCPServerStatus).mockResolvedValue();
  jest.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    const path = String(input).split("?")[0];
    if (path === "/api/admin/default-assistant/configuration")
      return json({
        tool_ids: mockToolIds,
        system_prompt: null,
        default_system_prompt: "",
      });
    if (path === "/api/admin/default-assistant" && init?.method === "PATCH") {
      if (mockDefaultSaveFails)
        return json({ detail: "Save failed" }, { status: 500 });
      const body = JSON.parse(String(init.body));
      mockDefaultWrites.push(body.tool_ids);
      mockToolIds = body.tool_ids;
      return json({
        tool_ids: mockToolIds,
        system_prompt: null,
        default_system_prompt: "",
      });
    }
    if (path === "/api/admin/mcp/server/7/tools/snapshots")
      return json([
        { id: 1, enabled: true },
        { id: 2, enabled: true },
        { id: 3, enabled: false },
      ]);
    return json(server);
  });
});
afterEach(() => jest.restoreAllMocks());

test("removes only this server tools from the default assistant", async () => {
  const user = setupUser();
  render(<MCPServerDetailPage serverId={7} />);
  const toggle = await screen.findByRole("switch", {
    name: messages.actions.addMcpModal.defaultChat.title,
  });
  expect(toggle).toBeChecked();
  await user.click(toggle);
  await waitFor(() => expect(toggle).not.toBeChecked());
  expect(mockDefaultWrites).toEqual([[99]]);
  expect(updateMCPServer).not.toHaveBeenCalled();
  expect(
    screen.getByRole("switch", {
      name: messages.actions.addMcpModal.craft.title,
    })
  ).toBeChecked();
});

test("retains the saved availability when its write fails", async () => {
  mockDefaultSaveFails = true;
  render(<MCPServerDetailPage serverId={7} />);
  const toggle = await screen.findByRole("switch", {
    name: messages.actions.addMcpModal.defaultChat.title,
  });
  await setupUser().click(toggle);
  await waitFor(() =>
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/admin/default-assistant",
      expect.objectContaining({ method: "PATCH" })
    )
  );
  await waitFor(() => expect(toggle).toBeEnabled());
  expect(toggle).toBeChecked();
});

test("hides Craft availability when Craft is unavailable", async () => {
  jest
    .mocked(useSettings)
    .mockReturnValue({ onyx_craft_available: false } as ReturnType<
      typeof useSettings
    >);
  render(<MCPServerDetailPage serverId={7} />);
  await screen.findByRole("switch", {
    name: messages.actions.addMcpModal.defaultChat.title,
  });
  expect(
    screen.queryByRole("switch", {
      name: messages.actions.addMcpModal.craft.title,
    })
  ).not.toBeInTheDocument();
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

test("guards page navigation for tool drafts and allows canceling discard", async () => {
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
  await user.click(
    screen.getByRole("link", { name: messages.actions.mcpDetail.back })
  );
  expect(await screen.findByRole("dialog")).toBeVisible();
  await user.click(
    screen.getByRole("button", {
      name: messages.chat.modals.unsavedChanges.cancelButton.label,
    })
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(mockPush).not.toHaveBeenCalled();
});

test("loads tools once after OAuth return and clears the callback query", async () => {
  mockSearchParams = new URLSearchParams("trigger_fetch=true");
  const { rerender } = render(<MCPServerDetailPage serverId={7} />);
  await waitFor(() => expect(refreshMCPServerTools).toHaveBeenCalledWith(7));
  rerender(<MCPServerDetailPage serverId={7} />);
  await waitFor(() =>
    expect(mockReplace).toHaveBeenCalledWith("/admin/mcp-actions/7?tab=tools", {
      scroll: false,
    })
  );
  expect(refreshMCPServerTools).toHaveBeenCalledTimes(1);
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

test("shows a partially selected server as available and preserves unrelated tools", async () => {
  mockToolIds = [2, 99];
  render(<MCPServerDetailPage serverId={7} />);
  const toggle = await screen.findByRole("switch", {
    name: messages.actions.addMcpModal.defaultChat.title,
  });
  await waitFor(() => expect(toggle).toBeChecked());
  const user = setupUser();
  await user.click(toggle);
  await waitFor(() => expect(toggle).not.toBeChecked());
  await user.click(toggle);
  await waitFor(() => expect(toggle).toBeChecked());
  expect(mockDefaultWrites).toEqual([[99], [99, 1, 2, 3]]);
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
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("link", { name: messages.actions.mcpDetail.back })
  );
  expect(await screen.findByRole("dialog")).toBeVisible();
});

test("saving server configuration stays on the page and clears its draft guard", async () => {
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
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(mockPush).not.toHaveBeenCalled();
});
