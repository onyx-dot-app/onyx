import { render, screen } from "@tests/setup/test-utils";
import { useLanguageModels } from "@/lib/languageModels/hooks";
import { PlaygroundRestrictedFeature } from "@/lib/playground/types";
import { useSettings } from "@/lib/settings/hooks";
import { useTierAtLeast } from "@/lib/tiers/hooks";
import Layout from "@/app/app/settings/layout";

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => "/app/settings/account",
}));
// Keep SWRConfig for the test providers; only the hook is stubbed.
jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  __esModule: true,
  default: () => ({ data: undefined }),
}));
jest.mock("@/hooks/useFederatedOAuthStatus", () => ({
  __esModule: true,
  default: () => ({ connectors: [] }),
}));
jest.mock("@/lib/tiers/hooks", () => ({
  ...jest.requireActual("@/lib/tiers/hooks"),
  useTierAtLeast: jest.fn(),
}));
jest.mock("@/lib/languageModels/hooks", () => ({
  useLanguageModels: jest.fn(),
}));
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: jest.fn(),
}));

const mockUseTierAtLeast = useTierAtLeast as jest.MockedFunction<
  typeof useTierAtLeast
>;
const mockUseLanguageModels = useLanguageModels as jest.MockedFunction<
  typeof useLanguageModels
>;
const mockUseSettings = useSettings as jest.MockedFunction<typeof useSettings>;

// The user provider mock has no permissions, so nothing else opens the tab:
// no tokens, no OAuth provider, no federated connectors, no visible model.
describe("settings layout, 3rd Party Access tab", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseTierAtLeast.mockReturnValue(true);
    mockUseLanguageModels.mockReturnValue({
      llmProviders: [{ model_configurations: [{ is_visible: false }] }],
      isLoading: false,
      error: undefined,
    } as unknown as ReturnType<typeof useLanguageModels>);
  });

  it("hides the tab when none of its sections has something to show", () => {
    const none: PlaygroundRestrictedFeature[] = [];
    mockUseSettings.mockReturnValue({
      oauth_provider_enabled: false,
      playground_restrictions: none,
    } as ReturnType<typeof useSettings>);

    render(
      <Layout>
        <div />
      </Layout>
    );

    expect(screen.queryByText("3rd Party Access")).not.toBeInTheDocument();
  });

  it("shows the tab when the playground restricts the gateway, so the notice is reachable", () => {
    mockUseTierAtLeast.mockReturnValue(false);
    mockUseSettings.mockReturnValue({
      oauth_provider_enabled: false,
      playground_restrictions: [PlaygroundRestrictedFeature.LLM_GATEWAY],
    } as ReturnType<typeof useSettings>);

    render(
      <Layout>
        <div />
      </Layout>
    );

    // Once in the narrow-screen select, once in the wide-screen tab list.
    expect(screen.getAllByText("3rd Party Access").length).toBeGreaterThan(0);
  });
});
