import { render, waitFor } from "@tests/setup/test-utils";
import MCPPageContent from "@/sections/actions/MCPPageContent";
import { MCPServerStatus } from "@/lib/tools/types";

const mockUpdateMCPServerStatus = jest.fn();
const mockRefreshMCPServerTools = jest.fn();
const mockMutateMcpServers = jest.fn();
const mockRouterReplace = jest.fn();
const mockToastSuccess = jest.fn();
const mockToastError = jest.fn();

// Regression for onyx-dot-app/onyx#14346: the OAuth return URL
// (?server_id=N&trigger_fetch=true) must start exactly one tool fetch.
const mockSearchParams = new URLSearchParams({
  server_id: "7",
  trigger_fetch: "true",
});

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockRouterReplace, push: jest.fn() }),
  usePathname: () => "/admin/actions",
  useSearchParams: () => mockSearchParams,
}));

// Stable identity, like SWR's cached data. A fresh object per render would
// spin the component's own effects instead of testing the trigger effect.
const mockMcpData = { mcp_servers: [] };

jest.mock("@/lib/tools/hooks", () => ({
  useAdminMcpServers: () => ({
    mcpData: mockMcpData,
    isLoading: false,
    mutateMcpServers: mockMutateMcpServers,
  }),
}));

jest.mock("@/lib/tools/svc", () => ({
  ...jest.requireActual("@/lib/tools/svc"),
  updateMCPServerStatus: (...args: unknown[]) =>
    mockUpdateMCPServerStatus(...args),
  refreshMCPServerTools: (...args: unknown[]) =>
    mockRefreshMCPServerTools(...args),
}));

jest.mock("@opal/layouts", () => ({
  ...jest.requireActual("@opal/layouts"),
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
    info: jest.fn(),
  },
}));

jest.mock("@/sections/actions/MCPActionCard", () => ({
  __esModule: true,
  default: () => <div data-testid="mcp-action-card" />,
}));
jest.mock("@/sections/actions/modals/MCPAuthenticationModal", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/sections/actions/modals/AddMCPServerModal", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/sections/actions/modals/DisconnectEntityModal", () => ({
  __esModule: true,
  default: () => null,
}));

beforeEach(() => {
  jest.clearAllMocks();
  mockUpdateMCPServerStatus.mockResolvedValue(undefined);
  mockRefreshMCPServerTools.mockResolvedValue([]);
  mockMutateMcpServers.mockResolvedValue(undefined);
});

test("trigger_fetch query param fetches tools exactly once", async () => {
  render(<MCPPageContent />);

  await waitFor(() => expect(mockToastSuccess).toHaveBeenCalledTimes(1));
  // Give any stray second run time to land before asserting the counts.
  await new Promise((resolve) => setTimeout(resolve, 50));

  expect(mockUpdateMCPServerStatus).toHaveBeenCalledTimes(1);
  expect(mockUpdateMCPServerStatus).toHaveBeenCalledWith(
    7,
    MCPServerStatus.FETCHING_TOOLS
  );
  expect(mockRefreshMCPServerTools).toHaveBeenCalledTimes(1);
  expect(mockRefreshMCPServerTools).toHaveBeenCalledWith(7);
  expect(mockToastSuccess).toHaveBeenCalledTimes(1);
  expect(mockToastError).not.toHaveBeenCalled();
  expect(mockRouterReplace).toHaveBeenCalledTimes(1);
});
