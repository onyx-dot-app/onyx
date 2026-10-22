/**
 * @jest-environment jsdom
 */

import { render, screen, setupUser, within } from "@tests/setup/test-utils";
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

/** The picker card whose title is `modelName`. */
async function findModelCard(modelName: string): Promise<HTMLElement> {
  const [title] = await screen.findAllByText(modelName, {
    selector: ":not([data-testid='current-embedding-model'] *)",
  });
  let card: HTMLElement | null = title ?? null;
  while (card && within(card).queryAllByRole("button").length === 0) {
    card = card.parentElement;
  }
  if (!card) throw new Error(`No card for ${modelName}`);
  return card;
}

const BIFROST_MODEL = "openai/text-embedding-3-small";

async function openModelPicker(user: ReturnType<typeof setupUser>) {
  await user.click(screen.getByRole("button", { name: "View All Models" }));
}

describe("IndexSettingsPage embedding model picker", () => {
  beforeEach(() => {
    mockState.currentModel = null;
    mockState.searchSettings = null;
    mockState.configuredProviders = [];
    jest
      .spyOn(global, "fetch")
      .mockImplementation(async (input: RequestInfo | URL) =>
        String(input).endsWith("/test-embedding")
          ? new Response(JSON.stringify({ dimension: 1536 }), { status: 200 })
          : new Response("{}", { status: 200 })
      );
  });

  afterEach(() => jest.restoreAllMocks());

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

    expect(
      within(await findModelCard(BIFROST_MODEL)).getByRole("button", {
        name: "Selected",
      })
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        `Switching to Bifrost / ${BIFROST_MODEL}. A full re-index will run.`
      )
    ).toBeInTheDocument();
  });

  it("shows a current Bifrost model as a current card", async () => {
    setCurrentModel(BIFROST_MODEL, EmbeddingProviderName.BIFROST, 1536);
    configureProviders(EmbeddingProviderName.BIFROST);
    const user = setupUser();
    render(<IndexSettingsPage />);
    await openModelPicker(user);

    expect(
      within(await findModelCard(BIFROST_MODEL)).getByRole("button", {
        name: "Current Model",
      })
    ).toBeInTheDocument();
    // The admin can still add a different model.
    expect(
      screen.getByText("Add configs for your Bifrost embedding providers.")
    ).toBeInTheDocument();
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
      within(await findModelCard("acme/embed-v2")).getByRole("button", {
        name: "Current Model",
      })
    ).toBeInTheDocument();
  });
});
