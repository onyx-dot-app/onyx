/** @jest-environment jsdom */
import {
  act,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import { Button, useModal } from "@opal/components";
import McpServerDialogs from "@/sections/actions/McpServerDialogs";
import {
  MCPServerStatus,
  MCPConnectionStatus,
  type MCPServer,
} from "@/lib/mcp/types";
import {
  updateMCPServer,
  updateMCPServerStatus,
  deleteMCPServer,
} from "@/lib/mcp/svc";

jest.mock("@/lib/mcp/svc");
jest.mock("@/components/IsPublicGroupSelector", () => ({
  IsPublicGroupSelector: () => null,
}));
jest.mock("@/sections/actions/modals/MCPAuthenticationModal", () => ({
  __esModule: true,
  default: function Authentication({
    mcpServer,
  }: {
    mcpServer: MCPServer | null;
  }) {
    const { isOpen, toggle } = useModal();
    return isOpen ? (
      <Button
        aria-description={mcpServer?.server_url}
        onClick={() => toggle(false)}
      >
        Close authentication
      </Button>
    ) : null;
  },
}));

const server: MCPServer = {
  id: 7,
  name: "Test MCP",
  server_url: "https://mcp.example.com",
  owner: "admin",
  connection_status: MCPConnectionStatus.CONNECTED,
  status: MCPServerStatus.CONNECTED,
  is_public: true,
  groups: [],
  users: [],
  tool_count: 2,
  permissions: { edit: true, delete: true, authenticate: true },
};

beforeEach(() => {
  jest.clearAllMocks();
  jest.mocked(updateMCPServer).mockResolvedValue(server);
  jest.mocked(updateMCPServerStatus).mockResolvedValue(undefined);
  jest.mocked(deleteMCPServer).mockResolvedValue(undefined);
});

it("keeps management open until source changes refresh", async () => {
  const user = setupUser();
  let finish: (() => void) | undefined;
  const refresh = new Promise<void>((resolve) => {
    finish = resolve;
  });
  const onChanged = jest.fn(() => refresh);
  const onClose = jest.fn();
  render(
    <McpServerDialogs
      servers={[server]}
      initialServer={server}
      onClosed={onClose}
      onChanged={onChanged}
    />
  );
  const name = await screen.findByDisplayValue("Test MCP");
  await user.clear(name);
  await user.type(name, "Renamed MCP");
  await user.click(screen.getByRole("button", { name: /save changes/i }));
  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  expect(updateMCPServer).toHaveBeenCalledWith(
    7,
    expect.objectContaining({ name: "Renamed MCP" })
  );
  expect(onClose).not.toHaveBeenCalled();
  await act(async () => {
    finish?.();
    await refresh;
  });
  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
});

it("keeps the inline workflow mounted while opening authentication", async () => {
  const user = setupUser();
  const onClose = jest.fn();
  const { rerender } = render(
    <McpServerDialogs
      servers={[server]}
      initialServer={server}
      onClosed={onClose}
      onChanged={jest.fn()}
    />
  );
  await user.click(
    await screen.findByRole("button", { name: /edit configs/i })
  );
  expect(onClose).not.toHaveBeenCalled();
  rerender(
    <McpServerDialogs
      servers={[{ ...server, server_url: "https://updated.example.com" }]}
      initialServer={server}
      onClosed={onClose}
      onChanged={jest.fn()}
    />
  );
  expect(
    screen.getByRole("button", { name: "Close authentication" })
  ).toHaveAttribute("aria-description", "https://updated.example.com");
  await user.click(
    await screen.findByRole("button", { name: "Close authentication" })
  );
  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
});

it("disconnects through the shared source workflow and refreshes Craft", async () => {
  const user = setupUser();
  const onChanged = jest.fn();
  const onClose = jest.fn();
  render(
    <McpServerDialogs
      servers={[server]}
      initialServer={server}
      onClosed={onClose}
      onChanged={onChanged}
    />
  );
  await user.click(
    await screen.findByRole("button", { name: /disconnect server/i })
  );
  expect(onClose).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: /^disconnect$/i }));
  await waitFor(() =>
    expect(updateMCPServerStatus).toHaveBeenCalledWith(
      7,
      MCPServerStatus.DISCONNECTED
    )
  );
  expect(onChanged).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
});

it("retains the delete confirmation on failure and retries the shared mutation", async () => {
  const user = setupUser();
  const onChanged = jest.fn();
  const onClosed = jest.fn();
  jest
    .mocked(deleteMCPServer)
    .mockRejectedValueOnce(new Error("Delete failed"))
    .mockResolvedValueOnce(undefined);
  render(
    <McpServerDialogs
      servers={[server]}
      initialServer={server}
      onChanged={onChanged}
      onClosed={onClosed}
    />
  );
  await user.click(
    await screen.findByRole("button", { name: /disconnect server/i })
  );
  await user.click(screen.getByRole("button", { name: "Disconnect & Delete" }));
  await waitFor(() => expect(deleteMCPServer).toHaveBeenCalledTimes(1));
  expect(onClosed).not.toHaveBeenCalled();
  expect(onChanged).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Disconnect & Delete" }));
  await waitFor(() => expect(onClosed).toHaveBeenCalledTimes(1));
  expect(onChanged).toHaveBeenCalledTimes(1);
});
