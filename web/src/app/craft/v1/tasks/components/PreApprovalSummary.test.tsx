import { render, screen } from "@tests/setup/test-utils";
import PreApprovalSummary from "@/app/craft/v1/tasks/components/PreApprovalSummary";
import { appFixture, mcpServerFixture } from "@/lib/skills/__fixtures__/picker";

const mockUseUserExternalApps = jest.fn();
const mockUseCraftMcpServers = jest.fn();

jest.mock("@/hooks/useUserExternalApps", () => ({
  __esModule: true,
  default: (enabled?: boolean) => mockUseUserExternalApps(enabled),
}));

jest.mock("@/lib/tools/hooks", () => ({
  useCraftMcpServers: (enabled?: boolean) => mockUseCraftMcpServers(enabled),
}));

describe("PreApprovalSummary", () => {
  beforeEach(() => {
    mockUseUserExternalApps.mockReturnValue({
      data: [appFixture({ id: 7, name: "Acme CRM", app_type: "CUSTOM" })],
      isLoading: false,
      error: undefined,
    });
    mockUseCraftMcpServers.mockReturnValue({
      data: {
        mcp_servers: [mcpServerFixture({ id: 7, name: "Acme MCP" })],
      },
      isLoading: false,
      error: undefined,
    });
  });

  it("resolves overlapping app and MCP ids from their separate catalogs", () => {
    render(<PreApprovalSummary appIds={[7]} mcpServerIds={[7, 99]} />);

    expect(screen.getByText("Acme CRM")).toBeInTheDocument();
    expect(screen.getByText("Acme MCP")).toBeInTheDocument();
    expect(screen.getByText("MCP server #99")).toBeInTheDocument();
  });

  it("waits for both catalogs instead of flashing raw ids", () => {
    mockUseCraftMcpServers.mockReturnValue({ isLoading: true });
    const { rerender } = render(
      <PreApprovalSummary appIds={[7]} mcpServerIds={[7]} />
    );

    expect(
      screen.queryByText("Pre-approved apps and MCP servers")
    ).not.toBeInTheDocument();

    mockUseCraftMcpServers.mockReturnValue({
      data: {
        mcp_servers: [mcpServerFixture({ id: 7, name: "Acme MCP" })],
      },
      isLoading: false,
    });
    rerender(<PreApprovalSummary appIds={[7]} mcpServerIds={[7]} />);

    expect(screen.getByText("Acme CRM")).toBeInTheDocument();
    expect(screen.getByText("Acme MCP")).toBeInTheDocument();
  });

  it("does not load or wait for an unused catalog", () => {
    mockUseCraftMcpServers.mockReturnValue({
      error: new Error("unused catalog failure"),
      isLoading: true,
    });

    render(<PreApprovalSummary appIds={[7]} mcpServerIds={[]} />);

    expect(screen.getByText("Acme CRM")).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Some pre-approval details couldn’t load. Refresh to try again."
      )
    ).not.toBeInTheDocument();
    expect(mockUseUserExternalApps).toHaveBeenCalledWith(true);
    expect(mockUseCraftMcpServers).toHaveBeenCalledWith(false);
  });

  it("distinguishes a catalog error from a missing grant", () => {
    mockUseCraftMcpServers.mockReturnValue({
      data: { mcp_servers: [] },
      error: new Error("catalog unavailable"),
      isLoading: false,
    });

    render(<PreApprovalSummary appIds={[7]} mcpServerIds={[99]} />);

    expect(screen.getByText("Acme CRM")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Some pre-approval details couldn’t load. Refresh to try again."
      )
    ).toBeInTheDocument();
    expect(screen.queryByText("MCP server #99")).not.toBeInTheDocument();
  });
});
