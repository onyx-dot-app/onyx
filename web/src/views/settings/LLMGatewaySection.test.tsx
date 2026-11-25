import { render, screen } from "@tests/setup/test-utils";
import { useTierAtLeast } from "@/lib/tiers/hooks";
import { useLanguageModels } from "@/lib/languageModels/hooks";
import { useSettings } from "@/lib/settings/hooks";
import { Tier } from "@/lib/tiers/types";
import LLMGatewaySection from "@/views/settings/LLMGatewaySection";
import { PlaygroundRestrictedFeature } from "@/lib/playground/types";

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
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ permissions: [] }),
}));
jest.mock("@/hooks/useCloudSubscription", () => ({
  useCloudSubscription: () => false,
}));
// The playground notice renders as Opal markdown. Under Jest, react-markdown's
// default export loads as a module object, so render the source text as is.
jest.mock("react-markdown", () => ({
  __esModule: true,
  default: ({ children }: { children?: string }) => children ?? null,
}));

const mockUseTierAtLeast = useTierAtLeast as jest.MockedFunction<
  typeof useTierAtLeast
>;
const mockUseLanguageModels = useLanguageModels as jest.MockedFunction<
  typeof useLanguageModels
>;
const mockUseSettings = useSettings as jest.MockedFunction<typeof useSettings>;

describe("LLMGatewaySection", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseTierAtLeast.mockReturnValue(true);
    mockUseSettings.mockReturnValue({
      isLoading: false,
      appName: "Onyx",
    } as ReturnType<typeof useSettings>);
    mockUseLanguageModels.mockReturnValue({
      llmProviders: [
        {
          id: 1,
          name: "OpenAI",
          provider_display_name: "OpenAI",
          model_configurations: [
            {
              name: "gpt-4o",
              effectiveDisplayName: "GPT-4o",
              is_visible: true,
              is_recommended_default: true,
            },
          ],
        },
      ],
      isLoading: false,
      error: undefined,
    } as unknown as ReturnType<typeof useLanguageModels>);
  });

  it("renders the Gateway for the Business minimum tier", () => {
    render(<LLMGatewaySection />);

    expect(mockUseTierAtLeast).toHaveBeenCalledWith(Tier.BUSINESS);
    expect(screen.getByText("Gateway URL")).toBeInTheDocument();
    expect(screen.getByText(/1 model is available/)).toBeInTheDocument();
  });

  it("renders nothing below Business", () => {
    mockUseTierAtLeast.mockReturnValue(false);

    const { container } = render(<LLMGatewaySection />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the user can see no model", () => {
    mockUseLanguageModels.mockReturnValue({
      llmProviders: [],
      isLoading: false,
      error: undefined,
    } as unknown as ReturnType<typeof useLanguageModels>);

    const { container } = render(<LLMGatewaySection />);

    expect(container).toBeEmptyDOMElement();
  });

  it("shows the disabled notice when an admin turned the gateway off", () => {
    mockUseSettings.mockReturnValue({
      isLoading: false,
      appName: "Onyx",
      llm_gateway_enabled: false,
    } as ReturnType<typeof useSettings>);

    render(<LLMGatewaySection />);

    expect(screen.getByText("LLM Gateway is off")).toBeInTheDocument();
    expect(screen.queryByText("Gateway URL")).not.toBeInTheDocument();
  });

  // ---------------------------------------------------------------------
  // Playground
  // ---------------------------------------------------------------------

  function stubPlayground(settings: Record<string, unknown> = {}) {
    mockUseSettings.mockReturnValue({
      isLoading: false,
      appName: "Onyx",
      llm_gateway_enabled: false,
      playground_restrictions: [PlaygroundRestrictedFeature.LLM_GATEWAY],
      ...settings,
    } as ReturnType<typeof useSettings>);
  }

  it("shows the playground notice when the playground restricts the gateway", () => {
    stubPlayground();

    render(<LLMGatewaySection />);

    expect(screen.getByText("Playground Limit")).toBeInTheDocument();
    expect(screen.queryByText("LLM Gateway is off")).not.toBeInTheDocument();
    expect(screen.queryByText("Gateway URL")).not.toBeInTheDocument();
  });

  it("shows the playground notice below the gateway tier and with no visible model", () => {
    stubPlayground({ llm_gateway_enabled: true });
    mockUseTierAtLeast.mockReturnValue(false);
    mockUseLanguageModels.mockReturnValue({
      llmProviders: [],
      isLoading: false,
      error: undefined,
    } as unknown as ReturnType<typeof useLanguageModels>);

    render(<LLMGatewaySection />);

    expect(screen.getByText("Playground Limit")).toBeInTheDocument();
  });

  it("shows the playground notice while the models are still loading", () => {
    stubPlayground();
    mockUseLanguageModels.mockReturnValue({
      llmProviders: undefined,
      isLoading: true,
      error: undefined,
    } as unknown as ReturnType<typeof useLanguageModels>);

    render(<LLMGatewaySection />);

    expect(screen.getByText("Playground Limit")).toBeInTheDocument();
  });

  it("shows the playground notice even when the model request failed", () => {
    stubPlayground();
    mockUseLanguageModels.mockReturnValue({
      llmProviders: undefined,
      isLoading: false,
      error: new Error("models unavailable"),
    } as unknown as ReturnType<typeof useLanguageModels>);

    render(<LLMGatewaySection />);

    expect(screen.getByText("Playground Limit")).toBeInTheDocument();
    expect(
      screen.queryByText("Could not load LLM Gateway")
    ).not.toBeInTheDocument();
  });
});
