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
import { toast } from "@opal/layouts";
import IndexSettingsPage from "@/views/admin/IndexSettingsPage";
import type { useConnectorIndexingStatusWithPagination } from "@/lib/hooks";
import type { LlmDefaults } from "@/lib/languageModels/types";
import {
  ApplicationStatus,
  QueryHistoryType,
  type AppSettings,
} from "@/lib/settings/types";
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
const mockAppSettings: AppSettings = {
  default_language: "en",
  anonymous_user_enabled: false,
  invite_only_enabled: false,
  notifications: [],
  needs_reindexing: false,
  gpu_enabled: false,
  application_status: ApplicationStatus.ACTIVE,
  auto_scroll: true,
  temperature_override_enabled: true,
  query_history_type: QueryHistoryType.NORMAL,
  image_extraction_and_analysis_enabled: false,
  image_analysis_max_size_mb: 20,
  hide_provider_grouping: false,
  enterprise: null,
  appName: "Onyx",
  logoUrl: null,
  vectorDbEnabled: false,
  isLoading: false,
  error: undefined,
};
const mockIndexingStatuses: Pick<
  ReturnType<typeof useConnectorIndexingStatusWithPagination>,
  "data" | "isLoading" | "isValidating" | "error"
> = {
  data: [],
  isLoading: false,
  isValidating: false,
  error: undefined,
};
const mockLlmDefaults: LlmDefaults = {
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
  reembeds: true,
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
    reduced_dimension: null,
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
const BIFROST_MODEL = "openai/text-embedding-3-small";

async function openModelPicker(user: ReturnType<typeof setupUser>) {
  await user.click(screen.getByRole("button", { name: "View All Models" }));
}

interface SentRequest {
  url: string;
  method: string;
  body: Record<string, unknown>;
}

describe("IndexSettingsPage embedding model picker", () => {
  let requests: SentRequest[];
  // A test embedding with this model fails, as with a retired model.
  let failingTestModel: string | null;

  beforeEach(() => {
    mockState.currentModel = null;
    mockState.searchSettings = null;
    mockState.configuredProviders = [];
    requests = [];
    failingTestModel = null;
    jest
      .spyOn(global, "fetch")
      .mockImplementation(
        async (input: RequestInfo | URL, init?: RequestInit) => {
          const body = init?.body ? JSON.parse(String(init.body)) : {};
          requests.push({
            url: String(input),
            method: init?.method ?? "GET",
            body,
          });
          if (String(input).endsWith("/test-embedding")) {
            if (body.model_name === failingTestModel) {
              return new Response(JSON.stringify({ detail: "model retired" }), {
                status: 400,
              });
            }
            return new Response(JSON.stringify({ dimension: 1536 }), {
              status: 200,
            });
          }
          return new Response("{}", { status: 200 });
        }
      );
  });

  afterEach(() => jest.restoreAllMocks());

  function testedModels(): unknown[] {
    return requests
      .filter((r) => r.url.endsWith("/test-embedding"))
      .map((r) => r.body.model_name);
  }

  it("shows a legacy current model as current, with a Legacy tag and an upgrade hint", async () => {
    setCurrentModel("nomic-ai/nomic-embed-text-v1", null, 768);
    const user = setupUser();
    render(<IndexSettingsPage />);

    const summary = await screen.findByTestId("current-embedding-model");
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
    expect(
      within(
        modelCard(
          EmbeddingProviderName.NVIDIA,
          "nvidia/Nemotron-3-Embed-1B-BF16"
        )
      ).getByText("GPU recommended")
    ).toBeInTheDocument();
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

  it("keeps the bring-your-own options in the collapsed Advanced section", async () => {
    setCurrentModel(
      "text-embedding-3-small",
      EmbeddingProviderName.OPENAI,
      1536
    );
    configureProviders(EmbeddingProviderName.OPENAI);
    const user = setupUser();
    render(<IndexSettingsPage />);
    await openModelPicker(user);

    const toggle = screen.getByRole("button", { name: BRING_YOUR_OWN });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByText("Add configs for your Azure embedding providers.")
    ).toBeNull();

    await user.click(toggle);

    expect(
      screen.getByText("Add configs for your LiteLLM embedding providers.")
    ).toBeInTheDocument();
    expect(
      screen.getByText("Add configs for your Azure embedding providers.")
    ).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Self-hosted" }));
    expect(
      screen.getByRole("button", { name: "Add Custom Model" })
    ).toBeInTheDocument();
  });

  it("shows a connected Bifrost model as a selected card and names it in the banner", async () => {
    setCurrentModel(
      "text-embedding-3-small",
      EmbeddingProviderName.OPENAI,
      1536
    );
    configureProviders(EmbeddingProviderName.OPENAI);
    const user = setupUser();
    render(<IndexSettingsPage />);
    await openModelPicker(user);
    await user.click(screen.getByRole("button", { name: BRING_YOUR_OWN }));
    await user.click(
      screen.getByText("Add configs for your Bifrost embedding providers.")
    );

    const dialog = await screen.findByRole("dialog", {
      name: /set up bifrost/i,
    });
    await user.type(
      within(dialog).getByLabelText(/base url/i),
      "http://bifrost:8080"
    );
    await user.type(
      within(dialog).getByLabelText(/model name/i),
      BIFROST_MODEL
    );
    await user.click(within(dialog).getByRole("button", { name: "Connect" }));

    const card = await screen.findByTestId(
      `embedding-model-card:${EmbeddingProviderName.BIFROST}:${BIFROST_MODEL}`
    );
    expect(
      within(card).getByRole("button", { name: "Selected" })
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        `Switching to Bifrost / ${BIFROST_MODEL}. A full re-index will run.`
      )
    ).toBeInTheDocument();
  });

  it("opens the bring-your-own section on a current Bifrost model and shows its card", async () => {
    setCurrentModel(BIFROST_MODEL, EmbeddingProviderName.BIFROST, 1536);
    configureProviders(EmbeddingProviderName.BIFROST);
    const user = setupUser();
    render(<IndexSettingsPage />);
    await openModelPicker(user);

    const toggle = screen.getByRole("button", { name: BRING_YOUR_OWN });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(
      within(modelCard(EmbeddingProviderName.BIFROST, BIFROST_MODEL)).getByRole(
        "button",
        { name: "Current Model" }
      )
    ).toBeInTheDocument();

    // The admin can still fold it.
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(
      queryModelCard(EmbeddingProviderName.BIFROST, BIFROST_MODEL)
    ).toBeNull();
  });

  it("finds a current bring-your-own model by its name", async () => {
    setCurrentModel("acme/embed-v2", EmbeddingProviderName.LITELLM, 768);
    configureProviders(EmbeddingProviderName.LITELLM);
    const user = setupUser();
    render(<IndexSettingsPage />);
    await openModelPicker(user);

    await user.type(
      screen.getByPlaceholderText("Search models..."),
      "acme/embed"
    );

    expect(
      within(
        modelCard(EmbeddingProviderName.LITELLM, "acme/embed-v2")
      ).getByRole("button", { name: "Current Model" })
    ).toBeInTheDocument();
  });

  it("edits the staged spec when it has the current model's name", async () => {
    const modelName = "acme/embed-v2";
    setCurrentModel(modelName, EmbeddingProviderName.LITELLM, 768);
    configureProviders(EmbeddingProviderName.LITELLM);
    const user = setupUser();
    render(<IndexSettingsPage />);
    await openModelPicker(user);

    await user.click(
      screen.getByText("Add configs for your LiteLLM embedding providers.")
    );
    const createDialog = await screen.findByRole("dialog");
    await user.type(
      within(createDialog).getByLabelText(/api base url/i),
      "https://litellm.example.com"
    );
    await user.type(within(createDialog).getByLabelText(/api key/i), "sk-new");
    await user.type(
      within(createDialog).getByLabelText(/model name/i),
      modelName
    );
    const createDim = within(createDialog).getByLabelText(/model dimension/i);
    await user.clear(createDim);
    await user.type(createDim, "1024");
    await user.click(
      within(createDialog).getByRole("button", { name: "Connect" })
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await user.click(screen.getByRole("button", { name: "Edit credentials" }));
    const editDialog = await screen.findByRole("dialog");
    expect(
      within(editDialog).getByLabelText(/model dimension/i)
    ).toHaveDisplayValue("1024");
  });

  it("keeps a current Azure deployment apart from the OpenAI model of the same name", async () => {
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

    const summary = await screen.findByTestId("current-embedding-model");
    expect(
      within(summary).queryByText(/OpenAI's large embedding model/)
    ).toBeNull();

    await openModelPicker(user);
    const openAiCard = modelCard(
      EmbeddingProviderName.OPENAI,
      "text-embedding-3-large"
    );
    await user.click(
      within(openAiCard).getByRole("button", { name: "Select Model" })
    );

    expect(
      within(openAiCard).getByRole("button", { name: "Selected" })
    ).toBeInTheDocument();
  });

  it("stages a custom model with a registry name as a custom model", async () => {
    setCurrentModel(GRANITE, null, 384);
    const user = setupUser();
    render(<IndexSettingsPage />);
    await openModelPicker(user);
    await user.click(screen.getByRole("button", { name: BRING_YOUR_OWN }));
    await user.click(screen.getByRole("button", { name: "Add Custom Model" }));

    const dialog = await screen.findByRole("dialog", {
      name: /set up custom model/i,
    });
    await user.type(
      within(dialog).getByLabelText(/model name/i),
      "voyageai/voyage-4-nano"
    );
    await user.type(within(dialog).getByLabelText(/model dimension/i), "1024");
    await user.click(within(dialog).getByRole("button", { name: "Connect" }));

    expect(
      await screen.findByRole("button", { name: "Apply & Re-index" })
    ).toBeInTheDocument();
    // The registry card of the same name is not the staged model.
    expect(
      within(
        modelCard(
          EmbeddingProviderName.VOYAGE_SELF_HOSTED,
          "voyageai/voyage-4-nano"
        )
      ).getByRole("button", { name: "Select Model" })
    ).toBeInTheDocument();
  });

  it("tests the credentials against the model being connected", async () => {
    setCurrentModel(
      "text-embedding-3-small",
      EmbeddingProviderName.OPENAI,
      1536
    );
    configureProviders(EmbeddingProviderName.OPENAI);
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

    await waitFor(() => expect(testedModels()).toEqual(["embed-v5.0-pro"]));
  });

  it("does not save new credentials that fail the test with the current model", async () => {
    setCurrentModel("embed-english-v3.0", EmbeddingProviderName.COHERE, 1024);
    configureProviders(EmbeddingProviderName.COHERE);
    failingTestModel = "embed-english-v3.0";
    const toastError = jest.spyOn(toast, "error");
    const user = setupUser();
    render(<IndexSettingsPage />);
    await openModelPicker(user);

    await user.click(screen.getByRole("button", { name: "Edit credentials" }));
    const dialog = await screen.findByRole("dialog", {
      name: /manage cohere/i,
    });
    const apiKeyInput = within(dialog).getByLabelText(/api key/i);
    await user.clear(apiKeyInput);
    await user.type(apiKeyInput, "co-new-key");
    await user.click(within(dialog).getByRole("button", { name: "Update" }));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("model retired")
    );
    expect(testedModels()).toEqual(["embed-english-v3.0"]);
    expect(requests.some((r) => r.method === "PUT")).toBe(false);
  });
});
