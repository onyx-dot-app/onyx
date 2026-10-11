/** Guards the connector-form MCP card: per-user OAuth server matching, the
 * register payload, the admin's connect in a new tab, and the permission gate. */

import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import PermSyncMcpServerCard, {
  findPerUserMcpServer,
} from "@/views/admin/connectors/AddConnectorPage/components/PermSyncMcpServerCard";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  MCPServerStatus,
  type MCPServer,
} from "@/lib/mcp/types";

jest.mock("@/lib/mcp/hooks", () => ({
  useAdminMcpServers: jest.fn(),
}));
jest.mock("@/lib/mcp/svc", () => ({
  upsertMCPServer: jest.fn(),
  startMCPUserOAuth: jest.fn(),
  getMCPUserOAuthNavigationUrl: jest.fn(),
}));
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: jest.fn(),
}));

const { useAdminMcpServers } = jest.requireMock("@/lib/mcp/hooks");
const { upsertMCPServer, startMCPUserOAuth, getMCPUserOAuthNavigationUrl } =
  jest.requireMock("@/lib/mcp/svc");
const { usePermissionAuthority } = jest.requireMock("@/lib/permissions/hooks");

const CONFIG = { name: "Notion MCP", url: "https://mcp.notion.com/mcp" };
const HOST = "mcp.notion.com";

function server(overrides: Partial<MCPServer> = {}): MCPServer {
  return {
    id: 7,
    name: "Notion MCP",
    server_url: "https://mcp.notion.com/mcp",
    owner: "admin@example.com",
    auth_type: MCPAuthenticationType.OAUTH,
    auth_performer: MCPAuthenticationPerformer.PER_USER,
    status: MCPServerStatus.CONNECTED,
    is_public: true,
    groups: [],
    users: [],
    tool_count: 0,
    ...overrides,
  };
}

function mockServers(servers: MCPServer[], error?: Error) {
  const mutateMcpServers = jest.fn().mockResolvedValue(undefined);
  useAdminMcpServers.mockReturnValue({
    mcpData: error ? null : { mcp_servers: servers },
    isLoading: false,
    error,
    mutateMcpServers,
  });
  return mutateMcpServers;
}

beforeEach(() => {
  jest.clearAllMocks();
  usePermissionAuthority.mockReturnValue({
    isGlobalHolder: true,
    isScopedManager: false,
  });
});

test("finds only a per-user OAuth server on the host, preferring the connected one", () => {
  const admin = server({ auth_performer: MCPAuthenticationPerformer.ADMIN });
  const other = server({ server_url: "https://mcp.example.com/mcp" });
  const first = server({ id: 1 });
  const connected = server({ id: 2, user_can_authenticate: true });
  expect(findPerUserMcpServer([admin, other, first], HOST)).toBe(first);
  expect(findPerUserMcpServer([admin, first, connected], HOST)).toBe(connected);
  expect(findPerUserMcpServer([server({ server_url: "::" })], HOST)).toBe(
    undefined
  );
});

test("registers the server as per-user OAuth and refreshes the list", async () => {
  const mutateMcpServers = mockServers([]);
  upsertMCPServer.mockResolvedValue({ data: { server_id: 7 }, error: null });
  const user = setupUser();
  render(<PermSyncMcpServerCard config={CONFIG} />);

  await user.click(screen.getByRole("button", { name: /register/i }));

  await waitFor(() => expect(mutateMcpServers).toHaveBeenCalled());
  expect(upsertMCPServer).toHaveBeenCalledWith(
    expect.objectContaining({
      name: "Notion MCP",
      server_url: "https://mcp.notion.com/mcp",
      auth_type: MCPAuthenticationType.OAUTH,
      auth_performer: MCPAuthenticationPerformer.PER_USER,
    })
  );
});

test("shows the register error and keeps the button", async () => {
  mockServers([]);
  upsertMCPServer.mockResolvedValue({ data: null, error: "nope" });
  const user = setupUser();
  render(<PermSyncMcpServerCard config={CONFIG} />);

  await user.click(screen.getByRole("button", { name: /register/i }));

  expect(await screen.findByText("nope")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /register/i })).toBeInTheDocument();
});

test("opens the admin's own connect in a new tab when registered but not connected", async () => {
  mockServers([server({ user_can_authenticate: false })]);
  startMCPUserOAuth.mockResolvedValue({
    status: "authorization_required",
    server_id: 7,
    authorization_url: "https://mcp.notion.com/authorize",
    redirect_url: "/admin/connectors/notion",
  });
  getMCPUserOAuthNavigationUrl.mockReturnValue(
    "https://mcp.notion.com/authorize"
  );
  const tab = { location: { href: "" }, close: jest.fn() };
  const open = jest
    .spyOn(window, "open")
    .mockImplementation(() => tab as unknown as Window);
  const user = setupUser();
  render(<PermSyncMcpServerCard config={CONFIG} />);

  await user.click(screen.getByRole("button", { name: /connect my account/i }));

  expect(open).toHaveBeenCalledWith("", "_blank");
  await waitFor(() =>
    expect(tab.location.href).toBe("https://mcp.notion.com/authorize")
  );
  expect(startMCPUserOAuth).toHaveBeenCalledWith(7, expect.any(String));
  expect(upsertMCPServer).not.toHaveBeenCalled();
  open.mockRestore();
});

test("shows the connect error and closes the blank tab", async () => {
  mockServers([server({ user_can_authenticate: false })]);
  startMCPUserOAuth.mockRejectedValue(new Error("auth down"));
  const tab = { location: { href: "" }, close: jest.fn() };
  const open = jest
    .spyOn(window, "open")
    .mockImplementation(() => tab as unknown as Window);
  const user = setupUser();
  render(<PermSyncMcpServerCard config={CONFIG} />);

  await user.click(screen.getByRole("button", { name: /connect my account/i }));

  expect(await screen.findByText("auth down")).toBeInTheDocument();
  expect(tab.close).toHaveBeenCalled();
  open.mockRestore();
});

test("shows connected without any button once the grant resolves", () => {
  mockServers([server({ user_can_authenticate: true })]);
  render(<PermSyncMcpServerCard config={CONFIG} />);

  expect(screen.getByText("Connected")).toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

test("hides the actions without the global action permission or when the listing fails", () => {
  usePermissionAuthority.mockReturnValue({
    isGlobalHolder: false,
    isScopedManager: true,
  });
  mockServers([]);
  const { unmount } = render(<PermSyncMcpServerCard config={CONFIG} />);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  unmount();

  usePermissionAuthority.mockReturnValue({
    isGlobalHolder: true,
    isScopedManager: false,
  });
  mockServers([], new Error("forbidden"));
  render(<PermSyncMcpServerCard config={CONFIG} />);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
