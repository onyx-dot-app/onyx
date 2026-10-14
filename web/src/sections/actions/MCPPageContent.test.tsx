import { renderHook } from "@testing-library/react";
import * as UserProvider from "@/providers/UserProvider";
import { Permission } from "@/lib/types";
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import MCPPageContent from "@/sections/actions/MCPPageContent";
import {
  MCPAuthenticationType,
  MCPServerStatus,
  type MCPServer,
} from "@/lib/mcp/types";
import messages from "@/i18n/messages/en.json";
import type { ToolSnapshot } from "@/lib/tools/types";

jest.mock("@/providers/UserProvider", () => {
  const actual = jest.requireActual<typeof UserProvider>(
    "@/providers/UserProvider"
  );
  return { ...actual, useUser: jest.fn(actual.useUser) };
});

const mockReplace = jest.fn();
const mockPush = jest.fn();
const mockRouter = { replace: mockReplace, push: mockPush };
let mockSearchParams = new URLSearchParams();
jest.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  usePathname: () => "/admin/mcp-actions",
  useSearchParams: () => mockSearchParams,
}));

const server: MCPServer = {
  id: 7,
  name: "Example MCP",
  description: "Workspace tools",
  server_url: "https://example.com/mcp",
  owner: "admin@example.com",
  auth_type: MCPAuthenticationType.NONE,
  status: MCPServerStatus.CREATED,
  is_public: true,
  groups: [],
  users: [],
  tool_count: 0,
  permissions: { edit: true, authenticate: true },
};

function mockNetwork(
  toolFailure = false,
  tools: ToolSnapshot[] = [],
  discoveredTools = tools
) {
  return jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/admin/mcp/servers")
      return new Response(JSON.stringify({ mcp_servers: [server] }));
    if (url === "/api/admin/mcp/servers/7")
      return new Response(JSON.stringify(server));
    if (url === "/api/settings")
      return new Response(JSON.stringify({ ee_features_enabled: false }));
    if (url === "/api/auth/type")
      return new Response(
        JSON.stringify({ auth_type: "basic", oauth_enabled: false })
      );
    if (url === "/api/admin/mcp/oauth/discover")
      return new Response(JSON.stringify({ status: "metadata_missing" }));
    if (url === "/api/admin/mcp/server")
      return new Response(JSON.stringify(server));
    if (url === "/api/admin/mcp/servers/create")
      return new Response(JSON.stringify({ server_id: 7 }));
    if (url.startsWith("/api/admin/mcp/server/7/status?"))
      return new Response("{}");
    if (url === "/api/admin/mcp/server/7/tools/snapshots?source=db")
      return new Response(JSON.stringify(tools));
    if (url === "/api/admin/mcp/server/7/tools/snapshots?source=mcp")
      return toolFailure
        ? new Response(JSON.stringify({ detail: "Tool listing failed" }), {
            status: 502,
          })
        : new Response(JSON.stringify(discoveredTools));
    throw new Error(`Unexpected request: ${url}`);
  });
}

beforeEach(() => {
  jest
    .mocked(UserProvider.useUser)
    .mockImplementation(
      jest.requireActual<typeof UserProvider>("@/providers/UserProvider")
        .useUser
    );
  const context = renderHook(() => UserProvider.useUser());
  const base = context.result.current;
  context.unmount();
  jest
    .mocked(UserProvider.useUser)
    .mockReturnValue({ ...base, permissions: [Permission.MANAGE_ACTIONS] });
  mockSearchParams = new URLSearchParams();
  mockReplace.mockClear();
  mockPush.mockClear();
});
afterEach(() => jest.restoreAllMocks());

test("filters server cards by description and restores the full list", async () => {
  mockNetwork();
  render(<MCPPageContent />);
  const user = setupUser();
  await screen.findByRole("article", { name: "Example MCP MCP server card" });
  const search = screen.getByPlaceholderText(
    messages.admin.shared.listHeader.search.placeholder
  );
  await user.type(search, "missing");
  expect(screen.queryByRole("article")).not.toBeInTheDocument();
  await user.clear(search);
  await user.type(search, "workspace");
  expect(screen.getByRole("article")).toBeVisible();
});

test("opens the server detail page instead of a modal", async () => {
  mockNetwork();
  render(<MCPPageContent />);
  await setupUser().click(
    await screen.findByRole("article", { name: "Example MCP MCP server card" })
  );
  expect(mockPush).toHaveBeenCalledWith("/admin/mcp-actions/7");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /Manage Example MCP/ })
  ).not.toBeInTheDocument();
});

test("forwards an OAuth return once to the detail page without starting discovery twice", async () => {
  mockSearchParams = new URLSearchParams("server_id=7&trigger_fetch=true");
  const network = mockNetwork();
  const { rerender } = render(<MCPPageContent />);
  await waitFor(() =>
    expect(mockReplace).toHaveBeenCalledWith(
      "/admin/mcp-actions/7?trigger_fetch=true"
    )
  );
  rerender(<MCPPageContent />);
  expect(mockReplace).toHaveBeenCalledTimes(1);
  expect(
    network.mock.calls.some(([url]) => String(url).includes("source=mcp"))
  ).toBe(false);
});

test.each(["invalid", "0", "7oops", "-1"])(
  "ignores invalid OAuth return server IDs: %s",
  async (id) => {
    mockSearchParams = new URLSearchParams(
      `server_id=${id}&trigger_fetch=true`
    );
    mockNetwork();
    render(<MCPPageContent />);
    await screen.findByRole("article");
    expect(mockReplace).not.toHaveBeenCalled();
  }
);

test.each([false, true])(
  "creation finishes on the detail page, keeping authentication open after discovery failures: %s",
  async (failure) => {
    const network = mockNetwork(failure);
    render(<MCPPageContent />);
    const user = setupUser();
    await user.click(
      await screen.findByRole("button", {
        name: messages.actions.mcpPage.addButton.label,
      })
    );
    await user.type(await screen.findByLabelText("Server Name"), "New server");
    await user.type(
      screen.getByRole("textbox", { name: /^MCP Server URL/ }),
      "https://example.com/mcp"
    );
    await user.click(
      screen.getByRole("button", { name: "Configure authentication" })
    );
    const save = await screen.findByRole("button", {
      name: messages.actions.mcpAuthModal.submitButton.label,
    });
    await waitFor(() => expect(save).toBeEnabled());
    await user.click(save);
    await waitFor(() =>
      expect(
        network.mock.calls.filter(
          ([url]) =>
            url === "/api/admin/mcp/server/7/tools/snapshots?source=mcp"
        )
      ).toHaveLength(1)
    );
    if (failure) {
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Tool listing failed"
      );
      expect(screen.getByRole("dialog")).toBeVisible();
      expect(mockPush).not.toHaveBeenCalled();
    } else {
      await waitFor(() =>
        expect(mockPush).toHaveBeenCalledWith("/admin/mcp-actions/7")
      );
    }
  }
);
