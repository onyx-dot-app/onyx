import { useState } from "react";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import PreApprovalPicker from "@/app/craft/v1/tasks/components/PreApprovalPicker";
import { appFixture, mcpServerFixture } from "@/lib/skills/__fixtures__/picker";

const mockUseUserExternalApps = jest.fn();
const mockUseCraftMcpServers = jest.fn();

jest.mock("@/hooks/useUserExternalApps", () => ({
  __esModule: true,
  default: () => mockUseUserExternalApps(),
}));

jest.mock("@/lib/tools/hooks", () => ({
  useCraftMcpServers: () => mockUseCraftMcpServers(),
}));

const APP = appFixture({
  id: 11,
  name: "Acme CRM",
  app_type: "CUSTOM",
});
const MCP_SERVER = mcpServerFixture({
  id: 22,
  name: "Acme MCP",
  craft_connected: false,
});

function StatefulPicker({
  initialMcpServerIds = [],
}: {
  initialMcpServerIds?: number[];
}) {
  const [appIds, setAppIds] = useState<number[]>([]);
  const [mcpServerIds, setMcpServerIds] =
    useState<number[]>(initialMcpServerIds);

  return (
    <PreApprovalPicker
      selectedAppIds={appIds}
      selectedMcpServerIds={mcpServerIds}
      onAppChange={setAppIds}
      onMcpServerChange={setMcpServerIds}
    />
  );
}

describe("PreApprovalPicker", () => {
  beforeEach(() => {
    mockUseUserExternalApps.mockReturnValue({ data: [APP] });
    mockUseCraftMcpServers.mockReturnValue({
      data: { mcp_servers: [MCP_SERVER] },
    });
  });

  it("keeps app and MCP selections independent for pointer and keyboard input", async () => {
    const user = setupUser();
    render(<StatefulPicker />);

    expect(screen.getByRole("region", { name: "Apps" })).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "MCP servers" })
    ).toBeInTheDocument();
    expect(screen.getByText("Connection required")).toBeInTheDocument();

    const app = screen.getByRole("checkbox", { name: "Acme CRM" });
    const mcpServer = screen.getByRole("checkbox", { name: "Acme MCP" });
    expect(app).not.toBeChecked();
    expect(mcpServer).not.toBeChecked();
    expect(mcpServer).toHaveAccessibleDescription("Connection required");

    await user.click(app);
    expect(app).toBeChecked();
    expect(mcpServer).not.toBeChecked();

    mcpServer.focus();
    await user.keyboard(" ");
    expect(app).toBeChecked();
    expect(mcpServer).toBeChecked();
  });

  it("shows a selected unavailable MCP server and lets the user remove it", async () => {
    const user = setupUser();
    mockUseCraftMcpServers.mockReturnValue({
      data: { mcp_servers: [] },
    });
    render(<StatefulPicker initialMcpServerIds={[99]} />);

    const unavailableServer = screen.getByRole("checkbox", {
      name: "MCP server #99",
    });
    expect(unavailableServer).toBeChecked();
    expect(unavailableServer).toHaveAccessibleDescription(
      "No longer available"
    );

    await user.click(unavailableServer);
    expect(
      screen.queryByRole("checkbox", { name: "MCP server #99" })
    ).not.toBeInTheDocument();
  });
});
