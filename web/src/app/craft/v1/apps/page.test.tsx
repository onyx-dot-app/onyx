import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import ExternalAppsPage from "@/app/craft/v1/apps/page";
import type { SkillsList } from "@/lib/skills/types";
import { SWR_KEYS } from "@/lib/swr-keys";

const mockUseSWR = jest.fn();
const mockUseUserSkills = jest.fn();
const mockMutateApps = jest.fn();
const mockMutateMcp = jest.fn();
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

describe("Apps associated-skill setup notice", () => {
  beforeEach(() => {
    mockMutateApps.mockReset();
    mockMutateMcp.mockReset();
    mockRefreshSkills.mockReset();
    mockDisconnectUserFromApp.mockReset();
    mockDisconnectUserFromApp.mockResolvedValue(undefined);
    mockUseSWR.mockImplementation((key: string) => {
      if (key === SWR_KEYS.buildExternalApps) {
        return {
          data: [
            {
              id: 42,
              name: "Acme CRM",
              app_type: "CUSTOM",
              credential_keys: [],
              credential_values: {},
              authenticated: true,
              supports_oauth: false,
            },
          ],
          mutate: mockMutateApps,
        };
      }
      return { data: { mcp_servers: [] }, mutate: mockMutateMcp };
    });
  });

  it("guides a connected user when no associated skill is selected", () => {
    mockUseUserSkills.mockReturnValue({
      data: skills(false, true),
      refresh: mockRefreshSkills,
    });

    render(<ExternalAppsPage />);

    expect(
      screen.getByText(
        "Connected · Not all associated skills are enabled. This app may not work correctly."
      )
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Skill setup required")).toBeInTheDocument();
    expect(screen.queryByLabelText("App ready")).not.toBeInTheDocument();
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
      screen.queryByText(
        "Connected · Not all associated skills are enabled. This app may not work correctly."
      )
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Review skills" })
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("App ready")).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Skill setup required")
    ).not.toBeInTheDocument();
  });

  it("does not claim an external app is ready before skills load", () => {
    mockUseUserSkills.mockReturnValue({
      data: undefined,
      refresh: mockRefreshSkills,
    });

    render(<ExternalAppsPage />);

    expect(screen.queryByLabelText("App ready")).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Skill setup required")
    ).not.toBeInTheDocument();
  });

  it("continues guiding the user until every associated skill is selected", () => {
    mockUseUserSkills.mockReturnValue({
      data: skills(true, false, false),
      refresh: mockRefreshSkills,
    });

    render(<ExternalAppsPage />);

    expect(
      screen.getByText(
        "Connected · Not all associated skills are enabled. This app may not work correctly."
      )
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
    expect(mockMutateMcp).toHaveBeenCalledTimes(1);
    expect(mockRefreshSkills).toHaveBeenCalledTimes(1);
  });
});
