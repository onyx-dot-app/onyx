import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import SkillPublishingCard from "@/views/admin/CraftPreferencesPage/SkillPublishingCard";
import { PluginPublishingPolicy } from "@/lib/settings/types";
import type { OrganizationLibraryDefaultPolicy } from "@/lib/skills/types";

const mockUpdateAdminSettings = jest.fn();
const mockSetDefaultAccess = jest.fn();
let mockPolicy: PluginPublishingPolicy | undefined = undefined;
let mockSharing: boolean | undefined = undefined;
let mockDefaultAccess: OrganizationLibraryDefaultPolicy | undefined = undefined;
let mockDefaultAccessFails = false;

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({
    plugin_publishing: mockPolicy,
    plugin_sharing: mockSharing,
    enterprise: null,
    appName: "Onyx",
    vectorDbEnabled: true,
    isLoading: false,
    error: undefined,
  }),
}));

jest.mock("@/lib/settings/svc", () => ({
  updateAdminSettings: (...args: unknown[]) => mockUpdateAdminSettings(...args),
}));

jest.mock("@/lib/skills/api", () => ({
  setOrganizationLibraryDefaultAccess: (...args: unknown[]) =>
    mockSetDefaultAccess(...args),
}));

jest.mock("@/lib/fetcher", () => ({
  errorHandlingFetcher: async () => {
    if (mockDefaultAccessFails) throw new Error("load failed");
    return mockDefaultAccess === undefined
      ? undefined
      : { installation_policy: mockDefaultAccess };
  },
}));

describe("SkillPublishingCard", () => {
  beforeEach(() => {
    mockPolicy = undefined;
    mockSharing = undefined;
    mockDefaultAccess = "AVAILABLE";
    mockDefaultAccessFails = false;
    mockUpdateAdminSettings.mockReset().mockResolvedValue(undefined);
    mockSetDefaultAccess.mockReset().mockResolvedValue(undefined);
  });

  it("shows Open by default and saves Requires review", async () => {
    const user = setupUser();
    render(<SkillPublishingCard />);

    expect(
      screen.getByText("Skill authors publish to the organization at once.")
    ).toBeVisible();
    await user.click(
      screen.getByRole("combobox", { name: "Skill Publishing" })
    );
    await user.click(screen.getByRole("option", { name: "Requires review" }));

    await waitFor(() =>
      expect(mockUpdateAdminSettings).toHaveBeenCalledWith({
        plugin_publishing: PluginPublishingPolicy.REQUIRES_REVIEW,
      })
    );
  });

  it("shows an error in place of Default Access when the read fails", async () => {
    mockDefaultAccessFails = true;
    render(<SkillPublishingCard />);

    const retry = await screen.findByText("Try again");
    expect(retry.closest("button")).not.toBeNull();
    expect(
      screen.queryByRole("combobox", { name: "Default Access" })
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Available to install")).not.toBeInTheDocument();
  });

  it("describes the saved setting", () => {
    mockPolicy = PluginPublishingPolicy.OFF;
    render(<SkillPublishingCard />);

    expect(
      screen.getByText("Only admins publish skills to the organization.")
    ).toBeVisible();
  });

  it("saves Not available as the default access, and offers no Required", async () => {
    const user = setupUser();
    render(<SkillPublishingCard />);

    expect(
      screen.getByText(
        "Applies to every published skill that doesn't have its own setting, including skills published later."
      )
    ).toBeVisible();
    const select = await screen.findByRole("combobox", {
      name: "Default Access",
    });
    await waitFor(() => expect(select).toBeEnabled());
    await user.click(select);
    expect(screen.queryByRole("option", { name: /^Required/ })).toBeNull();
    await user.click(screen.getByRole("option", { name: /^Not available/ }));

    await waitFor(() =>
      expect(mockSetDefaultAccess).toHaveBeenCalledWith("NOT_AVAILABLE")
    );
  });

  it("turns Sharing off", async () => {
    const user = setupUser();
    render(<SkillPublishingCard />);

    const sharing = screen.getByRole("switch");
    expect(sharing).toBeChecked();
    await user.click(sharing);

    await waitFor(() =>
      expect(mockUpdateAdminSettings).toHaveBeenCalledWith({
        plugin_sharing: false,
      })
    );
  });
});
