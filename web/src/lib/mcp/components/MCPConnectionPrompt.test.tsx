import { render, screen, setupUser } from "@tests/setup/test-utils";
import MCPConnectionPrompt from "@/lib/mcp/components/MCPConnectionPrompt";
import { useMcpAuthentication } from "@/lib/mcp/hooks";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  MCPServerStatus,
  type MCPServer,
} from "@/lib/mcp/types";
import type { ToolSnapshot } from "@/lib/tools/types";

jest.mock("@/lib/mcp/hooks");
const server: MCPServer = {
  id: 1,
  name: "Calendar",
  owner: "owner",
  server_url: "https://example.com/mcp",
  auth_type: MCPAuthenticationType.OAUTH,
  auth_performer: MCPAuthenticationPerformer.PER_USER,
  user_can_authenticate: false,
  status: MCPServerStatus.CONNECTED,
  is_public: true,
  groups: [],
  users: [],
  tool_count: 1,
};
const tool: ToolSnapshot = {
  id: 5,
  name: "events",
  display_name: "Events",
  description: "List events",
  definition: null,
  custom_headers: [],
  in_code_tool_id: null,
  passthrough_auth: false,
  mcp_server_id: 1,
  enabled: true,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: true,
};
const agent = { id: 0, tools: [tool] };
const toolConfiguration = { disabledToolIds: [], ready: true };
const authenticate = jest.fn();
const mockedUseAuthentication = jest.mocked(useMcpAuthentication);
function setServers(servers: MCPServer[]) {
  mockedUseAuthentication.mockReturnValue({
    servers,
    isLoading: false,
    error: undefined,
    refresh: jest.fn(),
    loadingServerId: null,
    authenticationError: null,
    authenticate,
    credentialRequest: null,
    cancelCredentialRequest: jest.fn(),
    submitCredentials: jest.fn(),
  });
}
beforeEach(() => {
  jest.clearAllMocks();
  setServers([server]);
});

describe("MCPConnectionPrompt", () => {
  it("opens the scoped list and starts authentication", async () => {
    const user = setupUser();
    render(
      <MCPConnectionPrompt
        agent={agent}
        toolConfiguration={toolConfiguration}
      />
    );
    await user.click(
      screen.getByRole("button", { name: "Tools need credentials (1)" })
    );
    expect(
      screen.getByRole("dialog", { name: /^Connect tools/ })
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Connect Calendar" }));
    expect(authenticate).toHaveBeenCalledWith(server);
  });
  it("shows the credential page in one dialog and returns to the list", async () => {
    const user = setupUser();
    const view = render(
      <MCPConnectionPrompt
        agent={agent}
        toolConfiguration={toolConfiguration}
      />
    );
    await user.click(
      screen.getByRole("button", { name: "Tools need credentials (1)" })
    );
    const backdrop = document.querySelector(".opal-modal-overlay");
    expect(backdrop).toBeInTheDocument();
    const onClose = jest.fn();
    mockedUseAuthentication.mockReturnValue({
      servers: [server],
      isLoading: false,
      error: undefined,
      refresh: jest.fn(),
      loadingServerId: null,
      authenticationError: null,
      authenticate,
      credentialRequest: { server, forceReauthentication: false },
      cancelCredentialRequest: onClose,
      submitCredentials: jest.fn(),
    });
    view.rerender(
      <MCPConnectionPrompt
        agent={agent}
        toolConfiguration={toolConfiguration}
      />
    );
    expect(document.querySelectorAll(".opal-modal-overlay")).toHaveLength(1);
    expect(document.querySelector(".opal-modal-overlay")).toBe(backdrop);
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.getByLabelText("API Key")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Connect Calendar" })
    ).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("API Key"), "unsaved");
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(document.querySelectorAll(".opal-modal-overlay")).toHaveLength(1);
    expect(document.querySelector(".opal-modal-overlay")).toBe(backdrop);
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.getByText("Discard unsaved changes?")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.getByLabelText("API Key")).toHaveValue("unsaved");
    await user.clear(screen.getByLabelText("API Key"));
    await user.click(screen.getByRole("button", { name: "Back to tools" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    setServers([server]);
    view.rerender(
      <MCPConnectionPrompt
        agent={agent}
        toolConfiguration={toolConfiguration}
      />
    );
    expect(document.querySelectorAll(".opal-modal-overlay")).toHaveLength(1);
    expect(document.querySelector(".opal-modal-overlay")).toBe(backdrop);
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: "Connect Calendar" })
    ).toBeInTheDocument();
  });

  it("retains connected rows and restores composer focus after success", async () => {
    const user = setupUser();
    const onConnectionsClosed = jest.fn();
    const view = render(
      <MCPConnectionPrompt
        agent={agent}
        toolConfiguration={toolConfiguration}
        onConnectionsClosed={onConnectionsClosed}
      />
    );
    await user.click(
      screen.getByRole("button", { name: "Tools need credentials (1)" })
    );
    setServers([{ ...server, user_can_authenticate: true }]);
    view.rerender(
      <MCPConnectionPrompt
        agent={agent}
        toolConfiguration={toolConfiguration}
        onConnectionsClosed={onConnectionsClosed}
      />
    );
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Tools need credentials (1)" })
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(onConnectionsClosed).toHaveBeenCalled();
  });
  it("does not warn for disabled tools or unrelated servers", () => {
    setServers([server, { ...server, id: 2, name: "Unrelated" }]);
    render(
      <MCPConnectionPrompt
        agent={agent}
        toolConfiguration={{ ...toolConfiguration, disabledToolIds: [tool.id] }}
      />
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
  it("does not offer unknown credentials or unsupported auth flows", () => {
    setServers([
      { ...server, user_can_authenticate: undefined },
      { ...server, auth_type: MCPAuthenticationType.PT_OAUTH },
      { ...server, auth_performer: MCPAuthenticationPerformer.ADMIN },
    ]);
    render(
      <MCPConnectionPrompt
        agent={agent}
        toolConfiguration={toolConfiguration}
      />
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
