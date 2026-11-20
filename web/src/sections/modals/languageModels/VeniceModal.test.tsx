import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import VeniceModal from "@/sections/modals/languageModels/VeniceModal";
import { LLMProviderView } from "@/lib/languageModels/types";
import { PointerEventsCheckLevel } from "@testing-library/user-event";

jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  __esModule: true,
  default: () => ({ data: undefined, error: undefined, isLoading: false }),
  useSWRConfig: () => ({ mutate: jest.fn() }),
}));

const VENICE_MODELS_URL = "/api/admin/llm/venice/available-models";

const savedProvider: LLMProviderView = {
  id: 7,
  name: "Venice",
  provider: "venice",
  api_key: "********",
  api_base: "https://api.venice.ai/api/v1",
  model_configurations: [
    {
      name: "z-ai-glm-5-3-flash",
      display_name: "GLM 5.3 Flash",
      is_visible: true,
      supports_chat: true,
      supports_decisions: false,
      supports_image_input: false,
      supports_reasoning: false,
      effectiveDisplayName: "GLM 5.3 Flash",
      max_input_tokens: null,
    },
  ],
  is_public: true,
  is_auto_mode: false,
  groups: [],
  personas: [],
  api_version: null,
  custom_config: null,
  deployment_name: null,
};

const veniceModels = [
  {
    name: "z-ai-glm-5-3-flash",
    display_name: "GLM 5.3 Flash",
    max_input_tokens: 200000,
    supports_image_input: false,
    supports_reasoning: true,
  },
  {
    name: "qwen-4-max",
    display_name: "Qwen 4 Max",
    max_input_tokens: 1000000,
    supports_image_input: true,
    supports_reasoning: true,
  },
];

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function mockFetch(veniceModelsResponse: () => Promise<Response>) {
  return jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) =>
      input === VENICE_MODELS_URL ? veniceModelsResponse() : jsonResponse([])
    );
}

describe("Venice provider modal", () => {
  afterEach(() => jest.restoreAllMocks());

  it("keeps Update disabled after refetching models on open", async () => {
    const fetchSpy = mockFetch(async () => jsonResponse(veniceModels));

    render(<VeniceModal existingLlmProvider={savedProvider} />);

    expect(await screen.findByText("Qwen 4 Max")).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledWith(
      VENICE_MODELS_URL,
      expect.objectContaining({ method: "POST" })
    );
    expect(screen.getByRole("button", { name: "Update" })).toBeDisabled();
  });

  it("logs a failed refetch and keeps the saved models", async () => {
    mockFetch(() => Promise.reject(new Error("network down")));
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});

    render(<VeniceModal existingLlmProvider={savedProvider} />);

    await waitFor(() =>
      expect(warn).toHaveBeenCalledWith(
        "Failed to refetch Venice models",
        "network down"
      )
    );
    expect(screen.getByText("GLM 5.3 Flash")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Update" })).toBeDisabled();
  });

  it("keeps edits made before the refetch finishes", async () => {
    let resolveModels: (response: Response) => void = () => {};
    mockFetch(
      () =>
        new Promise<Response>((resolve) => {
          resolveModels = resolve;
        })
    );
    const user = setupUser({
      pointerEventsCheck: PointerEventsCheckLevel.Never,
    });

    render(<VeniceModal existingLlmProvider={savedProvider} />);
    await user.clear(screen.getByLabelText(/display name/i));
    await user.type(screen.getByLabelText(/display name/i), "Renamed Venice");
    resolveModels(jsonResponse(veniceModels));

    expect(await screen.findByText("Qwen 4 Max")).toBeInTheDocument();
    expect(screen.getByLabelText(/display name/i)).toHaveValue(
      "Renamed Venice"
    );
    expect(screen.getByRole("button", { name: "Update" })).toBeEnabled();
  });
});
