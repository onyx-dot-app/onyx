import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import ExternalAppsPage from "@/app/craft/v1/apps/page";
import type { SkillsList } from "@/lib/skills/types";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  type MCPServer,
} from "@/lib/tools/types";
import type { ExternalAppUserResponse } from "@/app/craft/v1/apps/registry";
import { appFixture, mcpServerFixture } from "@/lib/skills/__fixtures__/picker";

const mockUseSWR = jest.fn();
const mockUseUserSkills = jest.fn();
const mockUseCraftMcpServers = jest.fn();
const mockMutateApps = jest.fn();
const mockRefreshMcp = jest.fn();
const mockRefreshSkills = jest.fn();
const mockDisconnectUserFromApp = jest.fn();

jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  __esModule: true,
  default: (...args: unknown[]) => mockUseSWR(...args),
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({ back: jest.fn(), push: jest.fn() }),
  usePathname: () => "/craft/v1/apps",
  useSearchParams: () => ({ get: () => null, has: () => false }),
}));

jest.mock("@/providers/UserProvider", () => ({
  ...jest.requireActual("@/providers/UserProvider"),
  useUser: () => ({ isAdmin: false }),
}));

jest.mock("@/hooks/useUserSkills", () => ({
  __esModule: true,
  default: () => mockUseUserSkills(),
}));

jest.mock("@/lib/tools/hooks", () => ({
  useCraftMcpServers: () => mockUseCraftMcpServers(),
}));

jest.mock("@/app/craft/services/externalAppsService", () => ({
  ...jest.requireActual("@/app/craft/services/externalAppsService"),
  disconnectUserFromApp: (...args: unknown[]) =>
    mockDisconnectUserFromApp(...args),
}));

function skills(
  associatedSkillEnabled: boolean,
  includeSelectedSameNameSkill = false,
  secondAssociatedSkillEnabled?: boolean
): SkillsList {
  const associatedSkill: SkillsList["customs"][number] = {
    source: "custom",
    id: "associated-skill-id",
    name: "crm-workflow",
    description: "Use the CRM workflow",
    is_available: null,
    unavailable_reason: null,
    is_valid: true,
    is_personal: false,
    enabled: associatedSkillEnabled,
    can_toggle: true,
    author_user_id: "owner-id",
    author_email: "owner@example.com",
    owner: { id: "owner-id", email: "owner@example.com" },
    ownership_vacant: false,
    created_at: null,
    updated_at: null,
    user_shares: [],
    group_shares: [],
    public_permission: "VIEWER",
    user_permission: "VIEWER",
    external_app: {
      external_app_id: 42,
      name: "Acme CRM",
      enabled: true,
      ready: true,
    },
  };
  const selectedSameNameSkill: SkillsList["customs"][number] = {
    ...associatedSkill,
    id: "standalone-skill-id",
    enabled: true,
    external_app: null,
  };
  const secondAssociatedSkill: SkillsList["customs"][number] = {
    ...associatedSkill,
    id: "second-associated-skill-id",
    name: "crm-reports",
    enabled: secondAssociatedSkillEnabled ?? false,
  };
  const customs = [associatedSkill];
  if (includeSelectedSameNameSkill) customs.push(selectedSameNameSkill);
  if (secondAssociatedSkillEnabled !== undefined) {
    customs.push(secondAssociatedSkill);
  }
  return {
    builtins: [],
    customs,
  };
}

const ACME_CRM_APP = appFixture({
  id: 42,
  name: "Acme CRM",
  app_type: "CUSTOM",
  credential_keys: [],
  credential_values: {},
  authenticated: true,
});

/** Pass-through OAuth, admin-performed — nothing for the user to connect. */
function mcpServer(overrides: Partial<MCPServer> = {}): MCPServer {
  return mcpServerFixture({
    id: 7,
    name: "Asana MCP",
    description: "Asana over MCP",
    auth_type: MCPAuthenticationType.PT_OAUTH,
    auth_performer: MCPAuthenticationPerformer.ADMIN,
    ...overrides,
  });
}

function mockEndpoints(
  apps: ExternalAppUserResponse[] = [ACME_CRM_APP],
  mcpServers: MCPServer[] = []
): void {
  mockUseSWR.mockImplementation(() => ({
    data: apps,
    mutate: mockMutateApps,
  }));
  mockUseCraftMcpServers.mockReturnValue({
    data: { mcp_servers: mcpServers },
    refresh: mockRefreshMcp,
  });
}

/** Queries scoped to the visible tab: every kind stays mounted so the page
 * keeps its geometry, so "on screen" means "inside the active panel". */
function activeTab() {
  return within(screen.getByRole("tabpanel"));
}

describe("Apps associated-skill setup notice", () => {
  beforeEach(() => {
    mockMutateApps.mockReset();
    mockRefreshMcp.mockReset();
    mockRefreshSkills.mockReset();
    mockDisconnectUserFromApp.mockReset();
    mockDisconnectUserFromApp.mockResolvedValue(undefined);
    mockEndpoints();
  });

  it("guides a connected user when no associated skill is selected", () => {
    mockUseUserSkills.mockReturnValue({
      data: skills(false, true),
      refresh: mockRefreshSkills,
    });

    render(<ExternalAppsPage />);

    expect(
      screen.getByText("Connected · not all associated skills are enabled")
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Skill setup required")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review skills" })).toHaveAttribute(
      "href",
      "/craft/v1/skills?externalAppId=42"
    );
  });

  it("does not nag after an associated skill is selected", () => {
    mockUseUserSkills.mockReturnValue({
      data: skills(true),
      refresh: mockRefreshSkills,
    });

    render(<ExternalAppsPage />);

    expect(
      screen.queryByText("Connected · not all associated skills are enabled")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Review skills" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Skill setup required")
    ).not.toBeInTheDocument();
  });

  it("does not warn about skills before they load", () => {
    mockUseUserSkills.mockReturnValue({
      data: undefined,
      refresh: mockRefreshSkills,
    });

    render(<ExternalAppsPage />);

    expect(
      screen.queryByLabelText("Skill setup required")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Review skills" })
    ).not.toBeInTheDocument();
  });

  it("continues guiding the user until every associated skill is selected", () => {
    mockUseUserSkills.mockReturnValue({
      data: skills(true, false, false),
      refresh: mockRefreshSkills,
    });

    render(<ExternalAppsPage />);

    expect(
      screen.getByText("Connected · not all associated skills are enabled")
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review skills" })).toHaveAttribute(
      "href",
      "/craft/v1/skills?externalAppId=42"
    );
  });

  it("refreshes app and skill state after disconnecting", async () => {
    const user = setupUser();
    mockUseUserSkills.mockReturnValue({
      data: skills(true),
      refresh: mockRefreshSkills,
    });

    render(<ExternalAppsPage />);
    await user.click(screen.getByRole("button", { name: "Disconnect" }));

    await waitFor(() =>
      expect(mockDisconnectUserFromApp).toHaveBeenCalledWith(42)
    );
    expect(mockMutateApps).toHaveBeenCalledTimes(1);
    expect(mockRefreshMcp).toHaveBeenCalledTimes(1);
    expect(mockRefreshSkills).toHaveBeenCalledTimes(1);
  });
});

describe("Apps vs MCP servers", () => {
  beforeEach(() => {
    mockMutateApps.mockReset();
    mockRefreshMcp.mockReset();
    mockRefreshSkills.mockReset();
    mockUseUserSkills.mockReturnValue({
      data: skills(true),
      refresh: mockRefreshSkills,
    });
  });

  it("separates apps from MCP servers so a row is never ambiguous", async () => {
    const user = setupUser();
    mockEndpoints([ACME_CRM_APP], [mcpServer()]);

    render(<ExternalAppsPage />);

    expect(activeTab().getByText("Acme CRM")).toBeInTheDocument();
    expect(activeTab().queryByText("Asana MCP")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /MCP servers/ }));

    expect(activeTab().getByText("Asana MCP")).toBeInTheDocument();
    expect(activeTab().queryByText("Acme CRM")).not.toBeInTheDocument();
  });

  it("does not claim a connected MCP server is skill-ready", async () => {
    const user = setupUser();
    mockEndpoints([ACME_CRM_APP], [mcpServer()]);

    render(<ExternalAppsPage />);
    await user.click(screen.getByRole("tab", { name: /MCP servers/ }));

    // MCP servers expose MCP tools, not skills, so neither skill glyph applies —
    // the green check used to render here purely because no skill data existed.
    expect(
      activeTab().queryByLabelText("Skill setup required")
    ).not.toBeInTheDocument();
    // Still listed as connected — the row's presence is the status.
    expect(activeTab().getAllByText("Connected").length).toBeGreaterThan(0);
    expect(
      activeTab().queryByText(/Not available for your account/)
    ).not.toBeInTheDocument();
  });

  it("does not show a pass-through OAuth server as connected when Craft cannot authenticate the user", async () => {
    const user = setupUser();
    // A password-login user has no login OAuth token, so the sandbox proxy
    // cannot authenticate them and Craft drops the server from the session.
    mockEndpoints([ACME_CRM_APP], [mcpServer({ craft_connected: false })]);

    render(<ExternalAppsPage />);
    await user.click(screen.getByRole("tab", { name: /MCP servers/ }));

    expect(activeTab().getByText("Asana MCP")).toBeInTheDocument();
    expect(activeTab().queryByText("Connected")).not.toBeInTheDocument();
    expect(
      activeTab().getByText(/Not available for your account/)
    ).toBeInTheDocument();
  });

  it("leads with connected cards, then orders the rest by name", () => {
    mockEndpoints([
      appFixture({
        id: 1,
        name: "Zulip",
        app_type: "CUSTOM",
        authenticated: true,
      }),
      appFixture({
        id: 2,
        name: "Asana",
        app_type: "CUSTOM",
        authenticated: false,
      }),
      appFixture({
        id: 3,
        name: "Monday",
        app_type: "CUSTOM",
        authenticated: true,
      }),
      appFixture({
        id: 4,
        name: "Basecamp",
        app_type: "CUSTOM",
        authenticated: false,
      }),
    ]);

    render(<ExternalAppsPage />);

    const names = activeTab()
      .getAllByText(/^(Zulip|Asana|Monday|Basecamp)$/)
      .map((node) => node.textContent);
    expect(names).toEqual(["Monday", "Zulip", "Asana", "Basecamp"]);
  });

  it("reserves the inactive kind's space so switching tabs cannot move the page", async () => {
    const user = setupUser();
    mockEndpoints([ACME_CRM_APP], [mcpServer()]);

    render(<ExternalAppsPage />);

    // Each kind's blurb and list stay mounted in a shared slot — that is what
    // holds the taller kind's height on either tab — but only the active kind
    // is visible and reachable.
    const hiddenState = (matcher: RegExp | string) =>
      screen
        .getByText(matcher)
        .closest("[aria-hidden]")
        ?.getAttribute("aria-hidden");

    expect(hiddenState(/Integrations Onyx supports/)).toBe("false");
    expect(hiddenState("Acme CRM")).toBe("false");
    expect(hiddenState(/Servers an admin made available/)).toBe("true");
    expect(hiddenState("Asana MCP")).toBe("true");

    await user.click(screen.getByRole("tab", { name: /MCP servers/ }));

    expect(hiddenState(/Integrations Onyx supports/)).toBe("true");
    expect(hiddenState("Acme CRM")).toBe("true");
    expect(hiddenState(/Servers an admin made available/)).toBe("false");
    expect(hiddenState("Asana MCP")).toBe("false");
  });

  it("reads built-in skills when deciding whether an app needs setup", () => {
    // Built-in providers' associated skills are built-in rows, so a map built
    // only from `customs` never sees them. (Built-ins are force-enabled in
    // practice; the disabled fixture is what makes the wiring observable.)
    const builtinSkill: SkillsList["builtins"][number] = {
      ...skills(false).customs[0]!,
      source: "builtin",
      id: "builtin-slack-skill",
      name: "slack",
      is_available: true,
      is_valid: null,
      enabled: false,
    };
    mockUseUserSkills.mockReturnValue({
      data: { builtins: [builtinSkill], customs: [] },
      refresh: mockRefreshSkills,
    });
    mockEndpoints([{ ...ACME_CRM_APP, app_type: "SLACK", name: "Slack" }], []);

    render(<ExternalAppsPage />);

    expect(screen.getByLabelText("Skill setup required")).toBeInTheDocument();
  });
});
