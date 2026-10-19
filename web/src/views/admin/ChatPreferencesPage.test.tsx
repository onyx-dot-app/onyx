import {
  makeProvider,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import ChatPreferencesPage from "@/views/admin/ChatPreferencesPage";
import {
  ApplicationStatus,
  QueryHistoryType,
  type AppSettings,
} from "@/lib/settings/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { usePermissionAuthority } from "@/lib/permissions/hooks";

jest.mock("@/lib/permissions/hooks", () => ({
  ...jest.requireActual<typeof import("@/lib/permissions/hooks")>(
    "@/lib/permissions/hooks"
  ),
  usePermissionAuthority: jest.fn(),
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: jest.fn() }),
  usePathname: () => "/admin/chat-preferences",
}));

jest.mock("@/lib/adminNavLabels", () => ({
  useAdminRouteTitle: () => () => "Chat Preferences",
}));

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => settings,
}));

const mockUseAdminLanguageModels = jest.fn();

jest.mock("@/lib/languageModels/hooks", () => ({
  useAdminLanguageModels: () => mockUseAdminLanguageModels(),
}));

const settings: AppSettings = {
  default_language: "en",
  anonymous_user_enabled: false,
  invite_only_enabled: false,
  notifications: [],
  needs_reindexing: false,
  gpu_enabled: false,
  application_status: ApplicationStatus.ACTIVE,
  auto_scroll: true,
  temperature_override_enabled: true,
  reasoning_override_enabled: true,
  query_history_type: QueryHistoryType.NORMAL,
  company_name: "Example team",
  enterprise: null,
  appName: "Onyx",
  logoUrl: null,
  vectorDbEnabled: false,
  isLoading: false,
  error: undefined,
};

describe("ChatPreferencesPage", () => {
  beforeEach(() => {
    jest
      .mocked(usePermissionAuthority)
      .mockReturnValue({ isGlobalHolder: true, isScopedManager: false });
    mockUseAdminLanguageModels.mockReset();
    mockUseAdminLanguageModels.mockReturnValue({
      llmProviders: [makeProvider({})],
      defaultChatNaming: null,
      defaultSearchSelection: null,
      modelPaging: undefined,
      refetch: jest.fn(),
      error: undefined,
    });
    jest.spyOn(global, "fetch").mockImplementation(async (input, init) => {
      if (input === "/api/admin/settings" && init?.method === "PATCH") {
        return new Response(null, { status: 204 });
      }
      let data: unknown;
      switch (input) {
        case SWR_KEYS.defaultAssistantConfig:
          data = {
            tool_ids: [],
            system_prompt: null,
            default_system_prompt: "",
          };
          break;
        case SWR_KEYS.mcpServers:
          data = { mcp_servers: [] };
          break;
        case SWR_KEYS.connectorStatus:
        case SWR_KEYS.tools:
        case SWR_KEYS.openApiTools:
          data = [];
          break;
        default:
          throw new Error(`Unexpected request: ${String(input)}`);
      }
      return new Response(JSON.stringify(data), {
        headers: { "Content-Type": "application/json" },
      });
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  test("shows model selection after chat behavior without a disclosure", async () => {
    render(<ChatPreferencesPage />);

    expect(screen.getByText("Reasoning Control")).toBeInTheDocument();
    expect(screen.getByText("Team Name")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Example team")).toBeInTheDocument();
    const heading = screen.getByText("Model selection");
    expect(
      screen.getByText("Reasoning Control").compareDocumentPosition(heading) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      heading.compareDocumentPosition(screen.getByText("Team Name")) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(mockUseAdminLanguageModels).toHaveBeenCalled();
    expect(screen.getByText("Chat naming model")).toBeInTheDocument();
    expect(screen.getByText("Search selection model")).toBeInTheDocument();
    expect(screen.getAllByPlaceholderText("Use Default model")).toHaveLength(2);
    expect(
      screen.queryByRole("button", { name: /^(Expand|Fold) Model selection$/ })
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Fast Model")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith(SWR_KEYS.defaultAssistantConfig)
    );
    expect(global.fetch).not.toHaveBeenCalledWith(
      SWR_KEYS.adminLlmProvidersPaged
    );
  });

  test("still saves a changed team name on blur", async () => {
    const user = setupUser();
    render(<ChatPreferencesPage />);

    const input = screen.getByDisplayValue("Example team");
    await user.clear(input);
    await user.type(input, "New team");
    await user.tab();

    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith("/api/admin/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: expect.stringContaining('"company_name":"New team"'),
      })
    );
  });
});
