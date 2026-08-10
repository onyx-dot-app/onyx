import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  ToolSnapshot,
} from "@/lib/tools/interfaces";
import MCPLineItem, {
  MCPServer,
} from "@/refresh-components/popovers/ActionsPopover/MCPLineItem";

const oauthServer: MCPServer = {
  id: 1,
  name: "Test MCP server",
  owner_email: "owner@example.com",
  server_url: "https://mcp.example.com",
  auth_type: MCPAuthenticationType.OAUTH,
  auth_performer: MCPAuthenticationPerformer.PER_USER,
  is_authenticated: false,
};

const tool: ToolSnapshot = {
  id: 1,
  name: "test_tool",
  display_name: "Test tool",
  description: "A test tool",
  definition: null,
  custom_headers: [],
  in_code_tool_id: null,
  passthrough_auth: false,
  enabled: true,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: true,
};

interface RenderMCPLineItemOptions {
  isAuthenticated?: boolean;
  tools?: ToolSnapshot[];
}

function renderMCPLineItem({
  isAuthenticated = false,
  tools = [],
}: RenderMCPLineItemOptions = {}) {
  const onAuthenticate = jest.fn();
  const onSelect = jest.fn();

  render(
    <MCPLineItem
      server={oauthServer}
      isActive={false}
      onSelect={onSelect}
      onAuthenticate={onAuthenticate}
      tools={tools}
      enabledTools={tools}
      isAuthenticated={isAuthenticated}
      isLoading={false}
    />
  );

  return { onAuthenticate, onSelect };
}

function getTrailingIndicator(row: HTMLElement): HTMLElement {
  const indicators = row.querySelectorAll<HTMLElement>("[aria-hidden='true']");
  const indicator = indicators.item(indicators.length - 1);
  if (!indicator) throw new Error("Expected a trailing MCP row indicator.");
  return indicator;
}

describe("MCPLineItem", () => {
  it("uses the row as the sole authentication target", async () => {
    const user = userEvent.setup();
    const { onAuthenticate, onSelect } = renderMCPLineItem();
    const row = screen.getByRole("button", { name: oauthServer.name });

    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(getTrailingIndicator(row)).toHaveClass("pointer-events-none");

    await user.click(row);

    expect(onAuthenticate).toHaveBeenCalledTimes(1);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("authenticates once per keyboard activation", async () => {
    const user = userEvent.setup();
    const { onAuthenticate, onSelect } = renderMCPLineItem();
    const row = screen.getByRole("button", { name: oauthServer.name });

    row.focus();
    await user.keyboard("{Enter}");

    expect(onAuthenticate).toHaveBeenCalledTimes(1);
    expect(onSelect).not.toHaveBeenCalled();

    await user.keyboard(" ");

    expect(onAuthenticate).toHaveBeenCalledTimes(2);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("uses the row as the sole selection target", async () => {
    const user = userEvent.setup();
    const { onAuthenticate, onSelect } = renderMCPLineItem({
      isAuthenticated: true,
      tools: [tool],
    });
    const row = screen.getByRole("button", { name: oauthServer.name });

    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(getTrailingIndicator(row)).toHaveClass("pointer-events-none");

    await user.click(row);

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onAuthenticate).not.toHaveBeenCalled();
  });
});
