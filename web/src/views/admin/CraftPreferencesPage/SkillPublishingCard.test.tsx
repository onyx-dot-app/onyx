import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import SkillPublishingCard from "@/views/admin/CraftPreferencesPage/SkillPublishingCard";
import { PluginPublishingPolicy } from "@/lib/settings/types";

const mockUpdateAdminSettings = jest.fn();
let mockPolicy: PluginPublishingPolicy | undefined = undefined;

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({
    plugin_publishing: mockPolicy,
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

describe("SkillPublishingCard", () => {
  beforeEach(() => {
    mockPolicy = undefined;
    mockUpdateAdminSettings.mockReset().mockResolvedValue(undefined);
  });

  it("shows Open by default and saves Requires review", async () => {
    const user = setupUser();
    render(<SkillPublishingCard />);

    expect(
      screen.getByText("Skill authors publish to the organization at once.")
    ).toBeVisible();
    await user.click(screen.getByRole("combobox"));
    await user.click(screen.getByRole("option", { name: "Requires review" }));

    await waitFor(() =>
      expect(mockUpdateAdminSettings).toHaveBeenCalledWith({
        plugin_publishing: PluginPublishingPolicy.REQUIRES_REVIEW,
      })
    );
  });

  it("describes the saved setting", () => {
    mockPolicy = PluginPublishingPolicy.OFF;
    render(<SkillPublishingCard />);

    expect(
      screen.getByText("Only admins publish skills to the organization.")
    ).toBeVisible();
  });
});
