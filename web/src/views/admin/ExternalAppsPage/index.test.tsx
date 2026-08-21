/**
 * @jest-environment jsdom
 */

import {
  act,
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import useSWR from "swr";
import ExternalAppsPage from "@/views/admin/ExternalAppsPage";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  BuiltInExternalAppDescriptor,
  ExternalAppAdminResponse,
} from "@/app/craft/v1/apps/registry";
import { MCPServer, MCPServerStatus } from "@/lib/tools/types";
import * as externalAppsService from "@/app/craft/services/externalAppsService";
import * as mcpService from "@/lib/tools/mcpService";

jest.mock("swr", () => ({
  __esModule: true,
  ...jest.requireActual("swr"),
  default: jest.fn(),
}));

jest.mock("@/app/craft/services/externalAppsService");
jest.mock("@/lib/tools/mcpService");

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn(), replace: mockRouterReplace }),
  useSearchParams: () => mockSearchParams,
  usePathname: () => "/admin/craft/apps",
}));

const mockUseSWR = useSWR as jest.MockedFunction<typeof useSWR>;
const mockMutateApps = jest.fn();
const mockRouterReplace = jest.fn();
let mockSearchParams = new URLSearchParams();

const APP: ExternalAppAdminResponse = {
  id: 1,
  name: "Custom app",
  app_type: "CUSTOM",
  upstream_url_patterns: [],
  auth_template: {},
  organization_credentials: {},
  credential_placeholder_keys: [],
  enabled: true,
  actions: [],
  associated_skills: [],
  is_onyx_managed: false,
};

const SLACK_DESCRIPTOR: BuiltInExternalAppDescriptor = {
  app_type: "SLACK",
  name: "Slack",
  upstream_url_patterns: [],
  auth_template: {},
  required_org_credential_fields: [],
  setup_instructions: "Create a Slack app.",
  actions: [],
};

const MCP_SERVER: MCPServer = {
  id: 7,
  name: "Atlassian",
  server_url: "https://mcp.atlassian.com/v1/sse",
  owner: "admin@example.com",
  status: MCPServerStatus.CONNECTED,
  is_public: true,
  groups: [],
  users: [],
  tool_count: 12,
  available_in_craft: true,
  tool_policies: {},
};

interface SWRData {
  apps?: ExternalAppAdminResponse[];
  descriptors?: BuiltInExternalAppDescriptor[];
  servers?: MCPServer[];
  /** Leave the MCP fetch unresolved (data undefined). */
  mcpPending?: boolean;
  appsValidating?: boolean;
}

function mockSWRData({
  apps = [APP],
  descriptors = [],
  servers = [],
  mcpPending = false,
  appsValidating = false,
}: SWRData) {
  mockUseSWR.mockImplementation((key) => {
    const data =
      key === SWR_KEYS.buildExternalAppsAdmin
        ? apps
        : key === SWR_KEYS.buildExternalAppsBuiltInOptions
          ? descriptors
          : key === SWR_KEYS.adminMcpServers
            ? mcpPending
              ? undefined
              : { mcp_servers: servers }
            : [];
    return {
      data,
      error: undefined,
      isLoading: false,
      isValidating:
        key === SWR_KEYS.buildExternalAppsAdmin ? appsValidating : false,
      mutate:
        key === SWR_KEYS.buildExternalAppsAdmin ? mockMutateApps : jest.fn(),
    } as ReturnType<typeof useSWR>;
  });
}

const appSwitch = () =>
  screen.getByRole("switch", { name: "Disable Custom app" });

describe("ExternalAppsPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockSearchParams = new URLSearchParams();
    mockSWRData({});
    jest.mocked(externalAppsService.updateExternalApp).mockResolvedValue(APP);
  });

  it("keeps app controls disabled until the refreshed app state arrives", async () => {
    const user = setupUser();
    let finishRefresh: (() => void) | undefined;
    mockMutateApps.mockReturnValue(
      new Promise<void>((resolve) => {
        finishRefresh = resolve;
      })
    );

    render(<ExternalAppsPage />);
    await user.click(appSwitch());

    await waitFor(() => {
      expect(externalAppsService.updateExternalApp).toHaveBeenCalledWith(1, {
        enabled: false,
      });
    });
    expect(appSwitch()).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Custom app actions" })
    ).toBeDisabled();

    await act(async () => finishRefresh?.());

    await waitFor(() => expect(appSwitch()).toBeEnabled());
  });

  it("splits apps and MCP servers into tabs with summary facts", async () => {
    const user = setupUser();
    mockSWRData({ servers: [MCP_SERVER] });
    jest.mocked(mcpService.updateMCPServer).mockResolvedValue(MCP_SERVER);

    render(<ExternalAppsPage />);

    // Apps tab is the default; the custom app row carries its tag and facts.
    expect(screen.getByRole("tab", { name: "Apps · 1" })).toBeInTheDocument();
    expect(screen.getByText("Custom")).toBeInTheDocument();
    expect(
      screen.getByText(
        "0 upstream patterns · no credentials · no custom skills"
      )
    ).toBeInTheDocument();
    expect(screen.queryByText(/12 tools/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "MCP servers · 1" }));
    expect(screen.getByText("12 tools")).toBeInTheDocument();

    await user.click(screen.getByRole("switch", { name: "Disable Atlassian" }));
    await waitFor(() => {
      expect(mcpService.updateMCPServer).toHaveBeenCalledWith(7, {
        available_in_craft: false,
      });
    });
  });

  it("keeps app management usable while the MCP list is pending", async () => {
    const user = setupUser();
    mockSWRData({ mcpPending: true });

    render(<ExternalAppsPage />);

    // Apps render immediately; the MCP tab carries no count and shows its own
    // loading state instead of a false "No MCP servers yet".
    expect(screen.getByRole("tab", { name: "Apps · 1" })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "MCP servers" }));
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("follows ?tab changes without a remount", () => {
    const { rerender } = render(<ExternalAppsPage />);
    expect(screen.getByRole("tab", { name: "Apps · 1" })).toHaveAttribute(
      "aria-selected",
      "true"
    );

    mockSearchParams = new URLSearchParams({ tab: "mcp" });
    rerender(<ExternalAppsPage />);
    expect(
      screen.getByRole("tab", { name: "MCP servers · 0" })
    ).toHaveAttribute("aria-selected", "true");
  });

  it("adds a provider through the catalog", async () => {
    const user = setupUser();
    mockSWRData({ descriptors: [SLACK_DESCRIPTOR] });

    render(<ExternalAppsPage />);
    // The catalog is the only add entry point — no permanent available section.
    expect(screen.queryByText("Slack")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add app" }));
    const catalog = screen.getByRole("dialog");
    expect(within(catalog).getByText("Slack")).toBeInTheDocument();
    expect(within(catalog).getByText("Custom app")).toBeInTheDocument();

    await user.click(within(catalog).getByRole("button", { name: "Add" }));
    expect(await screen.findByText("Add Slack")).toBeInTheDocument();
  });

  it("confirms retained skill behavior before deleting an app", async () => {
    const user = setupUser();
    mockSWRData({
      apps: [
        {
          ...APP,
          name: "Slack",
          app_type: "SLACK",
          associated_skills: [
            { id: "skill-a", name: "acme-lookup", is_valid: true },
            { id: "skill-b", name: "acme-write", is_valid: true },
          ],
        },
      ],
    });
    jest.mocked(externalAppsService.deleteExternalApp).mockResolvedValue();
    mockMutateApps.mockResolvedValue(undefined);

    render(<ExternalAppsPage />);
    await user.click(screen.getByRole("button", { name: "Slack actions" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(
      screen.getByText(
        "2 associated custom skills will be kept, unlinked from this app, and disabled for everyone."
      )
    ).toBeInTheDocument();
    expect(externalAppsService.deleteExternalApp).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Delete app" }));
    await waitFor(() =>
      expect(externalAppsService.deleteExternalApp).toHaveBeenCalledWith(1)
    );
  });

  it("keeps deep-linked app settings open during revalidation", async () => {
    const user = setupUser();
    mockSearchParams = new URLSearchParams({ editAppId: "1" });
    mockSWRData({});

    const { rerender } = render(<ExternalAppsPage />);

    expect(await screen.findByText("Edit Custom app")).toBeInTheDocument();
    expect(mockRouterReplace).not.toHaveBeenCalled();

    mockSWRData({ appsValidating: true });
    rerender(<ExternalAppsPage />);
    expect(screen.getByText("Edit Custom app")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(mockRouterReplace).toHaveBeenCalledWith("/admin/craft/apps");
  });
});
