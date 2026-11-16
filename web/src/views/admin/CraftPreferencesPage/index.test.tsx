import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import CraftPreferencesPage from "@/views/admin/CraftPreferencesPage";

const mockUpdateAdminSettings = jest.fn();

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({
    onyx_craft_available: true,
    craft_instructions: "Old instructions.",
    plugin_publishing: "OPEN",
    invite_only_enabled: false,
    isLoading: false,
    error: undefined,
  }),
}));

jest.mock("@/lib/settings/svc", () => ({
  updateAdminSettings: (...args: unknown[]) => mockUpdateAdminSettings(...args),
}));

jest.mock("@/lib/fetcher", () => ({
  errorHandlingFetcher: async () => ({ content: "Base instructions." }),
}));

jest.mock("@/lib/languageModels/hooks", () => ({
  useAdminLanguageModels: () => ({
    data: undefined,
    defaultText: null,
    isLoading: false,
  }),
}));

jest.mock("@/app/craft/components/ModelPickerButton", () => ({
  __esModule: true,
  default: () => null,
}));

describe("CraftPreferencesPage", () => {
  beforeEach(() => {
    mockUpdateAdminSettings.mockReset().mockResolvedValue(undefined);
  });

  it("saves only the Craft instructions", async () => {
    const user = setupUser();
    render(<CraftPreferencesPage />);

    const instructions = screen.getByDisplayValue("Old instructions.");
    await user.clear(instructions);
    await user.type(instructions, "New instructions.");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mockUpdateAdminSettings).toHaveBeenCalledWith({
        craft_instructions: "New instructions.",
      })
    );
  });
});
