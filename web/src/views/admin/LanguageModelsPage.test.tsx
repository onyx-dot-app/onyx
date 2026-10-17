import { render, screen, setupUser } from "@tests/setup/test-utils";
import LanguageModelsPage from "@/views/admin/LanguageModelsPage";
import type { LLMProviderView } from "@/lib/languageModels/types";
import { SWR_KEYS } from "@/lib/swr-keys";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ back: jest.fn() }),
  usePathname: () => "/admin/language-models",
}));

jest.mock("@/lib/adminNavLabels", () => ({
  useAdminRouteTitle: () => () => "Language Models",
}));

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({
    appName: "Onyx",
    hide_provider_grouping: false,
    model_routing_enabled: false,
  }),
}));

jest.mock("@/lib/analytics/hooks", () => ({
  PHFeatureFlag: { LANGUAGE_MODEL_CONFIGURATION_DISABLED: "disabled" },
  usePHFeatureFlag: () => false,
}));

jest.mock("@/views/admin/CostOverridesPanel", () => ({
  __esModule: true,
  default: () => null,
}));

const providers: LLMProviderView[] = [
  {
    id: 7,
    name: null,
    provider: "openai",
    api_key: null,
    api_base: null,
    api_version: null,
    custom_config: null,
    is_public: true,
    is_auto_mode: false,
    groups: [],
    personas: [],
    deployment_name: null,
    model_configurations: [
      {
        id: 11,
        name: "gpt-4o",
        display_name: "GPT-4o",
        effectiveDisplayName: "GPT-4o",
        is_visible: true,
        max_input_tokens: null,
        supports_image_input: true,
        supports_reasoning: false,
      },
      {
        id: 12,
        name: "gpt-4o-mini",
        display_name: "GPT-4o Mini",
        effectiveDisplayName: "GPT-4o Mini",
        is_visible: false,
        max_input_tokens: null,
        supports_image_input: false,
        supports_reasoning: false,
      },
    ],
  },
];

providers.push({
  id: 8,
  name: "Search provider",
  provider: "openai",
  api_key: null,
  api_base: null,
  api_version: null,
  custom_config: null,
  is_public: true,
  is_auto_mode: false,
  groups: [],
  personas: [],
  deployment_name: null,
  model_configurations: [
    {
      id: 21,
      name: "search-mini",
      display_name: "Search Mini",
      effectiveDisplayName: "Search Mini",
      is_visible: false,
      max_input_tokens: null,
      supports_image_input: false,
      supports_reasoning: false,
    },
  ],
});

describe("LanguageModelsPage", () => {
  beforeEach(() => {
    jest.spyOn(global, "fetch").mockImplementation(async (input) => {
      if (input === SWR_KEYS.adminLlmProvidersPaged) {
        return new Response(
          JSON.stringify({
            providers,
            default_text: { provider_id: 7, model_name: "gpt-4o" },
            default_vision: null,
            default_chat_naming: { provider_id: 7, model_name: "gpt-4o-mini" },
            default_search_selection: {
              provider_id: 8,
              model_name: "search-mini",
            },
            default_craft: null,
          }),
          { headers: { "Content-Type": "application/json" } }
        );
      }
      if (input === SWR_KEYS.llmRouterModels) return new Response("[]");
      throw new Error(`Unexpected request: ${String(input)}`);
    });
  });
  afterEach(() => jest.restoreAllMocks());

  test("keeps task model settings out of Language Models and hidden models out of chat defaults", async () => {
    const user = setupUser();
    render(<LanguageModelsPage />);
    await screen.findByDisplayValue("GPT-4o");
    expect(screen.queryByText("Task-specific models")).not.toBeInTheDocument();
    expect(screen.queryByText("Optional task models")).not.toBeInTheDocument();
    expect(screen.queryByText("Chat naming model")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Search selection model")
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Fast background model")).not.toBeInTheDocument();
    await user.click(screen.getByDisplayValue("GPT-4o"));
    expect(
      screen.getByRole("option", { name: /^GPT-4o$/ })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: /GPT-4o Mini/ })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: /Search Mini/ })
    ).not.toBeInTheDocument();
  });
});
