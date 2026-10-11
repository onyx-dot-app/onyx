/** Guards the connector-form MCP card: per-user OAuth server matching, the
 * register payload, the registered state, and the permission gate. */

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
}));
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: jest.fn(),
}));

const { useAdminMcpServers } = jest.requireMock("@/lib/mcp/hooks");
const { upsertMCPServer } = jest.requireMock("@/lib/mcp/svc");
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

test("finds only a per-user OAuth server on the host", () => {
  const admin = server({ auth_performer: MCPAuthenticationPerformer.ADMIN });
  const other = server({ server_url: "https://mcp.example.com/mcp" });
  const match = server();
  expect(findPerUserMcpServer([admin, other, match], HOST)).toBe(match);
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

test("shows registered without any button once the server exists", () => {
  mockServers([server()]);
  render(<PermSyncMcpServerCard config={CONFIG} />);

  expect(screen.getByText("Registered")).toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

test("hides the register button without the global action permission or when the listing fails", () => {
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
