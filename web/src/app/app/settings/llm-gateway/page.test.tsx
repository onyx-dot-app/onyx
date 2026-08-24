import { render, screen, waitFor } from "@testing-library/react";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { useLLMProviders } from "@/lib/languageModels/hooks";
import { useSettings } from "@/lib/settings/hooks";
import { Tier } from "@/lib/settings/types";
import LLMGatewayPage from "@/app/app/settings/llm-gateway/page";

const mockReplace = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
}));
jest.mock("@/hooks/useTierAtLeast", () => ({
  useTierAtLeast: jest.fn(),
}));
jest.mock("@/lib/languageModels/hooks", () => ({
  useLLMProviders: jest.fn(),
}));
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: jest.fn(),
}));
jest.mock("@/views/SettingsPage", () => ({
  LLMGatewaySettings: () => <div>Gateway settings</div>,
}));

const mockUseTierAtLeast = useTierAtLeast as jest.MockedFunction<
  typeof useTierAtLeast
>;
const mockUseLLMProviders = useLLMProviders as jest.MockedFunction<
  typeof useLLMProviders
>;
const mockUseSettings = useSettings as jest.MockedFunction<typeof useSettings>;

describe("LLMGatewayPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseTierAtLeast.mockReturnValue(true);
    mockUseSettings.mockReturnValue({ isLoading: false } as ReturnType<
      typeof useSettings
    >);
    mockUseLLMProviders.mockReturnValue({
      llmProviders: [{ model_configurations: [{ is_visible: true }] }],
      isLoading: false,
      error: undefined,
    } as unknown as ReturnType<typeof useLLMProviders>);
  });

  it("renders the Gateway for the Business minimum tier", () => {
    render(<LLMGatewayPage />);

    expect(mockUseTierAtLeast).toHaveBeenCalledWith(Tier.BUSINESS);
    expect(screen.getByText("Gateway settings")).toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("redirects users below Business", async () => {
    mockUseTierAtLeast.mockReturnValue(false);

    render(<LLMGatewayPage />);

    expect(screen.queryByText("Gateway settings")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(mockReplace).toHaveBeenCalledWith("/app/settings/general")
    );
  });
});
