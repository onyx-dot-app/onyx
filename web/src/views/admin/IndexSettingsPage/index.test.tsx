/**
 * @jest-environment jsdom
 */

import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import IndexSettingsPage from "@/views/admin/IndexSettingsPage";
import {
  EmbeddingProviderName,
  type ConfiguredEmbeddingProvider,
  type EmbeddingModelResponse,
  type ReindexProgress,
  type SavedSearchSettings,
  VectorQuantization,
} from "@/lib/searchSettings/types";

jest.mock("next/navigation", () => ({
  useRouter: () => ({
    push: jest.fn(),
    replace: jest.fn(),
    refresh: jest.fn(),
  }),
  usePathname: () => "/admin/configuration/search",
  useSearchParams: () => new URLSearchParams(),
}));

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => mockAppSettings,
}));

jest.mock("@/lib/adminNavLabels", () => ({
  useAdminRouteTitle: () => (route: { title: string }) => route.title,
}));

// No requireActual: the real module has an import cycle through the
// language-model modals.
jest.mock("@/lib/hooks", () => ({
  useConnectorIndexingStatusWithPagination: () => mockIndexingStatuses,
}));

jest.mock("@/lib/languageModels/hooks", () => ({
  ...jest.requireActual("@/lib/languageModels/hooks"),
  useLlmDefaults: () => mockLlmDefaults,
}));

jest.mock("@/lib/searchSettings/hooks", () => ({
  ...jest.requireActual("@/lib/searchSettings/hooks"),
  useCurrentEmbeddingModel: () => ({
    data: mockState.currentModel,
    isLoading: false,
  }),
  useCurrentSearchSettings: () => ({
    data: mockState.searchSettings,
    isLoading: false,
  }),
  useSecondarySearchSettings: () => ({ data: null }),
  useReindexProgress: () => ({ data: mockReindexProgress }),
  useConfiguredEmbeddingProviders: () => ({
    data: mockState.configuredProviders,
  }),
}));

// Stable objects: the page memoizes on these, as it does on SWR data.
const mockAppSettings = {
  appName: "Onyx",
  image_extraction_and_analysis_enabled: false,
  image_analysis_max_size_mb: 20,
  hide_provider_grouping: false,
};
const mockIndexingStatuses = {
  data: [],
  isLoading: false,
  isValidating: false,
  error: undefined,
};
const mockLlmDefaults = {
  llmProviders: [],
  hasAnyLlm: false,
  hasAnyVisionLlm: false,
  defaultLlm: null,
  defaultVision: null,
  isLoading: false,
};
const mockReindexProgress: ReindexProgress = {
  total: 0,
  waiting: 0,
  in_progress: 0,
  completed: 0,
  failed: 0,
  paused: 0,
};

interface MockState {
  currentModel: EmbeddingModelResponse | null;
  searchSettings: SavedSearchSettings | null;
  configuredProviders: ConfiguredEmbeddingProvider[];
}
const mockState: MockState = {
  currentModel: null,
  searchSettings: null,
  configuredProviders: [],
};

function setCurrentModel(
  modelName: string,
  providerType: EmbeddingProviderName | null,
  modelDim: number
) {
  const current: EmbeddingModelResponse = {
    model_name: modelName,
    model_dim: modelDim,
    normalize: providerType === null,
    query_prefix: "",
    passage_prefix: "",
    provider_type: providerType,
    api_key: null,
    api_url: null,
    index_name: "danswer_chunk",
  };
  mockState.currentModel = current;
  mockState.searchSettings = {
    ...current,
    index_name: current.index_name,
    multipass_indexing: false,
    enable_contextual_rag: false,
    contextual_rag_model_configuration_id: null,
    multilingual_expansion: [],
    disable_rerank_for_streaming: false,
    api_url: null,
    num_rerank: 0,
    reduced_dimension: null,
    vector_quantization: VectorQuantization.NONE,
    rerank_model_name: null,
    rerank_provider_type: null,
    rerank_api_key: null,
    rerank_api_url: null,
    use_port_flow: true,
  };
}

function configureProviders(...providerTypes: EmbeddingProviderName[]) {
  mockState.configuredProviders = providerTypes.map((provider_type) => ({
    provider_type,
    api_key: "sk-****",
    api_url: null,
    api_version: null,
    deployment_name: null,
  }));
}

function modelCard(providerName: EmbeddingProviderName, modelName: string) {
  return screen.getByTestId(
    `embedding-model-card:${providerName}:${modelName}`
  );
}

function queryModelCard(
  providerName: EmbeddingProviderName,
  modelName: string
) {
  return screen.queryByTestId(
    `embedding-model-card:${providerName}:${modelName}`
  );
}

const BRING_YOUR_OWN = "Advanced: bring your own model or proxy";
const GRANITE = "ibm-granite/granite-embedding-97m-multilingual-r2";

async function openModelPicker(user: ReturnType<typeof setupUser>) {
  await user.click(screen.getByRole("button", { name: "View All Models" }));
}

describe("IndexSettingsPage embedding model picker", () => {
  beforeEach(() => {
    mockState.currentModel = null;
    mockState.searchSettings = null;
    mockState.configuredProviders = [];
  });

  it("shows a legacy current model as current, with a Legacy tag and an upgrade hint", async () => {
    setCurrentModel("nomic-ai/nomic-embed-text-v1", null, 768);
    const user = setupUser();
    render(<IndexSettingsPage />);

    const summary = await screen.findByTestId("current-embedding-model");
    expect(
      within(summary).getByText("nomic-ai/nomic-embed-text-v1")
    ).toBeInTheDocument();
    expect(within(summary).getByText("Legacy")).toBeInTheDocument();
    expect(
      within(summary).getByText(/This is a legacy model/)
    ).toBeInTheDocument();

    await openModelPicker(user);

    const card = modelCard(
      EmbeddingProviderName.NOMIC,
      "nomic-ai/nomic-embed-text-v1"
    );
    expect(
      within(card).getByRole("button", { name: "Current Model" })
    ).toBeInTheDocument();
    expect(within(card).getByText("Legacy")).toBeInTheDocument();
    // Other legacy models stay hidden; the new ones are selectable.
    expect(
      queryModelCard(EmbeddingProviderName.MICROSOFT, "intfloat/e5-base-v2")
    ).toBeNull();
    expect(
      within(modelCard(EmbeddingProviderName.IBM, GRANITE)).getByRole(
        "button",
        { name: "Select Model" }
      )
    ).toBeInTheDocument();
  });

  it("lists only selectable self-hosted models on a fresh install", async () => {
    setCurrentModel(GRANITE, null, 384);
    const user = setupUser();
    render(<IndexSettingsPage />);

    const summary = await screen.findByTestId("current-embedding-model");
    expect(within(summary).getByText(GRANITE)).toBeInTheDocument();
    expect(within(summary).queryByText("Legacy")).toBeNull();

    await openModelPicker(user);

    expect(
      within(modelCard(EmbeddingProviderName.IBM, GRANITE)).getByRole(
        "button",
        { name: "Current Model" }
      )
    ).toBeInTheDocument();
    const nemotron = modelCard(
      EmbeddingProviderName.NVIDIA,
      "nvidia/Nemotron-3-Embed-1B-BF16"
    );
    expect(within(nemotron).getByText("GPU recommended")).toBeInTheDocument();
    expect(
      modelCard(
        EmbeddingProviderName.VOYAGE_SELF_HOSTED,
        "voyageai/voyage-4-nano"
      )
    ).toBeInTheDocument();
    for (const [provider, name] of [
      [EmbeddingProviderName.NOMIC, "nomic-ai/nomic-embed-text-v1"],
      [EmbeddingProviderName.MICROSOFT, "intfloat/e5-small-v2"],
      [EmbeddingProviderName.GTE, "thenlper/gte-small"],
    ] as const) {
      expect(queryModelCard(provider, name)).toBeNull();
    }
  });

  it("does not find a hidden legacy model by search", async () => {
    setCurrentModel(GRANITE, null, 384);
    const user = setupUser();
    render(<IndexSettingsPage />);
    await openModelPicker(user);

    await user.type(screen.getByPlaceholderText("Search models..."), "e5");

    expect(
      await screen.findByText("No self-hosted models found")
    ).toBeInTheDocument();
  });

  it("keeps Add Custom Model in the collapsed Advanced section", async () => {
    setCurrentModel(GRANITE, null, 384);
    const user = setupUser();
    render(<IndexSettingsPage />);
    await openModelPicker(user);

    const toggle = screen.getByRole("button", { name: BRING_YOUR_OWN });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByRole("button", { name: "Add Custom Model" })
    ).toBeNull();

    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByRole("button", { name: "Add Custom Model" })
    ).toBeInTheDocument();
  });

  it("lists the new cloud models, hides legacy ones and keeps LiteLLM and Azure behind Advanced", async () => {
    setCurrentModel(
      "text-embedding-3-small",
      EmbeddingProviderName.OPENAI,
      1536
    );
    configureProviders(EmbeddingProviderName.OPENAI);
    const user = setupUser();
    render(<IndexSettingsPage />);
    await openModelPicker(user);

    expect(
      within(
        modelCard(EmbeddingProviderName.COHERE, "embed-v5.0-pro")
      ).getByRole("button", { name: "Connect" })
    ).toBeInTheDocument();
    expect(
      modelCard(EmbeddingProviderName.GOOGLE, "gemini-embedding-2")
    ).toBeInTheDocument();
    expect(
      queryModelCard(EmbeddingProviderName.COHERE, "embed-english-v3.0")
    ).toBeNull();
    expect(
      queryModelCard(EmbeddingProviderName.GOOGLE, "text-embedding-005")
    ).toBeNull();
    expect(
      queryModelCard(EmbeddingProviderName.VOYAGE, "voyage-large-2-instruct")
    ).toBeNull();
    expect(
      screen.queryByText("Add configs for your LiteLLM embedding providers.")
    ).toBeNull();

    await user.click(screen.getByRole("button", { name: BRING_YOUR_OWN }));

    expect(
      screen.getByText("Add configs for your LiteLLM embedding providers.")
    ).toBeInTheDocument();
    expect(
      screen.getByText("Add configs for your Azure embedding providers.")
    ).toBeInTheDocument();
  });

  it("shows a current Azure deployment as current in its own group, not as the OpenAI model of the same name", async () => {
    setCurrentModel(
      "text-embedding-3-large",
      EmbeddingProviderName.AZURE,
      1536
    );
    configureProviders(EmbeddingProviderName.AZURE);
    const user = setupUser();
    render(<IndexSettingsPage />);

    const summary = await screen.findByTestId("current-embedding-model");
    expect(
      within(summary).queryByText(/OpenAI's large embedding model/)
    ).toBeNull();

    await openModelPicker(user);

    // The Advanced section opens on its own for a bring-your-own current model.
    expect(
      screen.getByRole("button", { name: BRING_YOUR_OWN })
    ).toHaveAttribute("aria-expanded", "true");
    expect(
      within(
        modelCard(EmbeddingProviderName.AZURE, "text-embedding-3-large")
      ).getByRole("button", { name: "Current Model" })
    ).toBeInTheDocument();
    expect(
      within(
        modelCard(EmbeddingProviderName.OPENAI, "text-embedding-3-large")
      ).queryByRole("button", { name: "Current Model" })
    ).toBeNull();
  });

  it("shows a current custom self-hosted model as current in the Advanced section", async () => {
    setCurrentModel("BAAI/bge-small-en-v1.5", null, 384);
    const user = setupUser();
    render(<IndexSettingsPage />);
    await openModelPicker(user);

    expect(
      within(
        modelCard(EmbeddingProviderName.CUSTOM, "BAAI/bge-small-en-v1.5")
      ).getByRole("button", { name: "Current Model" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Add Custom Model" })
    ).toBeInTheDocument();
  });

  it("tests the credentials against the model being connected", async () => {
    setCurrentModel(
      "text-embedding-3-small",
      EmbeddingProviderName.OPENAI,
      1536
    );
    configureProviders(EmbeddingProviderName.OPENAI);
    const requests: { url: string; body: Record<string, unknown> }[] = [];
    const originalFetch = global.fetch;
    global.fetch = jest.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        requests.push({
          url: String(input),
          body: init?.body ? JSON.parse(String(init.body)) : {},
        });
        return new Response("{}", { status: 200 });
      }
    );

    try {
      const user = setupUser();
      render(<IndexSettingsPage />);
      await openModelPicker(user);

      await user.click(
        within(
          modelCard(EmbeddingProviderName.COHERE, "embed-v5.0-pro")
        ).getByRole("button", { name: "Connect" })
      );
      const dialog = await screen.findByRole("dialog", {
        name: /set up cohere/i,
      });
      await user.type(within(dialog).getByLabelText(/api key/i), "co-key");
      await user.click(within(dialog).getByRole("button", { name: "Connect" }));

      await waitFor(() =>
        expect(
          requests.find((r) => r.url.endsWith("/test-embedding"))?.body
        ).toMatchObject({
          provider_type: "cohere",
          model_name: "embed-v5.0-pro",
        })
      );
    } finally {
      global.fetch = originalFetch;
    }
  });

  it("stages a registry model that has the name of the current Azure deployment", async () => {
    setCurrentModel(
      "text-embedding-3-large",
      EmbeddingProviderName.AZURE,
      1536
    );
    configureProviders(
      EmbeddingProviderName.AZURE,
      EmbeddingProviderName.OPENAI
    );
    const user = setupUser();
    render(<IndexSettingsPage />);
    await openModelPicker(user);

    await user.click(
      within(
        modelCard(EmbeddingProviderName.OPENAI, "text-embedding-3-large")
      ).getByRole("button", { name: "Select Model" })
    );

    expect(
      within(
        modelCard(EmbeddingProviderName.OPENAI, "text-embedding-3-large")
      ).getByRole("button", { name: "Selected" })
    ).toBeInTheDocument();
    expect(
      within(
        modelCard(EmbeddingProviderName.AZURE, "text-embedding-3-large")
      ).getByRole("button", { name: "Current Model" })
    ).toBeInTheDocument();
  });

  it("keeps a cloud group with saved credentials when all its models are hidden", async () => {
    setCurrentModel("embed-v5.0-pro", EmbeddingProviderName.COHERE, 2048);
    configureProviders(
      EmbeddingProviderName.COHERE,
      EmbeddingProviderName.VOYAGE
    );
    const user = setupUser();
    render(<IndexSettingsPage />);
    await openModelPicker(user);

    // Voyage cloud has only legacy models, but its saved key can still be
    // edited or disconnected.
    expect(screen.getByRole("link", { name: "Voyage" })).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "Edit credentials" })
    ).toHaveLength(2);
    expect(
      queryModelCard(EmbeddingProviderName.VOYAGE, "voyage-large-2-instruct")
    ).toBeNull();
  });

  it("drops a cloud group with no visible models and no saved credentials", async () => {
    setCurrentModel("embed-v5.0-pro", EmbeddingProviderName.COHERE, 2048);
    configureProviders(EmbeddingProviderName.COHERE);
    const user = setupUser();
    render(<IndexSettingsPage />);
    await openModelPicker(user);

    expect(screen.queryByRole("link", { name: "Voyage" })).toBeNull();
  });

  it("saves new credentials for a retired current model when the default model works", async () => {
    setCurrentModel("embed-english-v3.0", EmbeddingProviderName.COHERE, 1024);
    configureProviders(EmbeddingProviderName.COHERE);
    const requests: {
      url: string;
      method: string;
      body: Record<string, unknown>;
    }[] = [];
    const originalFetch = global.fetch;
    global.fetch = jest.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const body = init?.body ? JSON.parse(String(init.body)) : {};
        requests.push({
          url: String(input),
          method: init?.method ?? "GET",
          body,
        });
        if (
          String(input).endsWith("/test-embedding") &&
          body.model_name === "embed-english-v3.0"
        ) {
          return new Response(JSON.stringify({ detail: "model retired" }), {
            status: 400,
          });
        }
        return new Response("{}", { status: 200 });
      }
    );
    try {
      const user = setupUser();
      render(<IndexSettingsPage />);
      await openModelPicker(user);

      await user.click(
        screen.getByRole("button", { name: "Edit credentials" })
      );
      const dialog = await screen.findByRole("dialog", {
        name: /manage cohere/i,
      });
      const apiKeyInput = within(dialog).getByLabelText(/api key/i);
      await user.clear(apiKeyInput);
      await user.type(apiKeyInput, "co-new-key");
      await user.click(within(dialog).getByRole("button", { name: "Update" }));

      await waitFor(() =>
        expect(requests.some((r) => r.method === "PUT")).toBe(true)
      );
      expect(
        requests
          .filter((r) => r.url.endsWith("/test-embedding"))
          .map((r) => r.body.model_name)
      ).toEqual(["embed-english-v3.0", ""]);
    } finally {
      global.fetch = originalFetch;
    }
  });
});
