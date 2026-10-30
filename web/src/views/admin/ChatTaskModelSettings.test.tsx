import {
  act,
  deferred,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import { toast } from "@opal/layouts";
import {
  ChatNamingModelSetting,
  SearchDecisionModelSetting,
} from "@/views/admin/ChatTaskModelSettings";
import DecisionModelSetting from "@/views/admin/DecisionModelSetting";
import type { DefaultModel, LLMProviderView } from "@/lib/languageModels/types";
import { SWR_KEYS } from "@/lib/swr-keys";

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({
    appName: "Onyx",
    hide_provider_grouping: false,
    model_routing_enabled: false,
  }),
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
        name: "gpt-6-sol",
        display_name: "GPT-6 Sol",
        effectiveDisplayName: "GPT-6 Sol",
        is_visible: true,
        max_input_tokens: null,
        supports_image_input: true,
        supports_reasoning: false,
      },
      {
        id: 12,
        name: "gpt-6-luna",
        display_name: "GPT-6 Luna",
        effectiveDisplayName: "GPT-6 Luna",
        is_visible: true,
        max_input_tokens: null,
        supports_image_input: false,
        supports_reasoning: false,
      },
      {
        id: 13,
        name: "gpt-legacy",
        display_name: "GPT Legacy",
        effectiveDisplayName: "GPT Legacy",
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
      is_visible: true,
      max_input_tokens: null,
      supports_image_input: false,
      supports_reasoning: false,
    },
  ],
});

function TaskModels() {
  return (
    <>
      <ChatNamingModelSetting />
      <SearchDecisionModelSetting />
    </>
  );
}

async function renderTaskModels(): Promise<void> {
  render(<TaskModels />);
  await screen.findByText("Chat Naming Model");
}

// Rows render in order: chat naming, then search decision model.
function taskSelector(row: 0 | 1): HTMLElement {
  const selector = screen.getAllByRole("combobox")[row];
  if (!selector) throw new Error(`Missing task model selector ${row}`);
  return selector;
}

describe("ChatTaskModelSettings", () => {
  let defaultChatNaming: DefaultModel | null;
  let defaultSearchSelection: DefaultModel | null;
  let decisionModel: DefaultModel | null;
  let mutationResponse: () => Promise<Response>;
  let searchMutationResponse: () => Promise<Response>;
  let listedProviders: LLMProviderView[];
  let listingResponse: (() => Promise<Response>) | null;
  let hasDecisionProviders: boolean;

  beforeEach(() => {
    defaultChatNaming = null;
    defaultSearchSelection = null;
    decisionModel = null;
    listedProviders = providers;
    listingResponse = null;
    hasDecisionProviders = true;
    mutationResponse = async () => new Response(null, { status: 204 });
    searchMutationResponse = async () => new Response(null, { status: 204 });
    jest.spyOn(toast, "success").mockReturnValue("success-toast");
    jest.spyOn(toast, "error").mockReturnValue("error-toast");
    jest.spyOn(global, "fetch").mockImplementation(async (input, init) => {
      if (input === SWR_KEYS.decisionModel) {
        if (init?.method === "POST")
          decisionModel = { provider_id: 7, model_name: "decisions" };
        if (init?.method === "DELETE") decisionModel = null;
        return new Response(
          JSON.stringify({
            model: decisionModel,
            providers: hasDecisionProviders
              ? [
                  {
                    ...providers[0],
                    model_configurations: [
                      {
                        id: 31,
                        name: "decisions",
                        display_name: "Decision Model A",
                        is_visible: false,
                        max_input_tokens: null,
                        supports_image_input: false,
                        supports_reasoning: false,
                        supports_chat: false,
                        supports_decisions: true,
                      },
                    ],
                  },
                ]
              : [],
          })
        );
      }
      if (input === "/api/admin/llm/default-chat-naming") {
        const response = await mutationResponse();
        if (response.ok) {
          defaultChatNaming =
            init?.method === "DELETE"
              ? null
              : { provider_id: 7, model_name: "gpt-6-luna" };
        }
        return response;
      }
      if (input === "/api/admin/llm/default-search-selection") {
        const response = await searchMutationResponse();
        if (response.ok) {
          defaultSearchSelection =
            init?.method === "DELETE"
              ? null
              : { provider_id: 8, model_name: "search-mini" };
        }
        return response;
      }
      if (input === SWR_KEYS.adminLlmProvidersPaged) {
        if (listingResponse) return listingResponse();
        return new Response(
          JSON.stringify({
            providers: listedProviders,
            default_text: { provider_id: 7, model_name: "gpt-6-sol" },
            default_vision: null,
            default_chat_naming: defaultChatNaming,
            default_search_selection: defaultSearchSelection,
            default_craft: null,
          }),
          { headers: { "Content-Type": "application/json" } }
        );
      }
      if (input === SWR_KEYS.llmRouterModels) {
        return new Response("[]", {
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  test("waits for provider data before rendering task controls", async () => {
    const pending = deferred<Response>();
    listingResponse = () => pending.promise;
    render(<TaskModels />);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    await act(async () =>
      pending.resolve(
        new Response(
          JSON.stringify({
            providers,
            default_text: null,
            default_vision: null,
            default_chat_naming: null,
            default_search_selection: null,
            default_craft: null,
          })
        )
      )
    );
    expect(await screen.findByText("Chat Naming Model")).toBeInTheDocument();
  });

  test("offers provider setup when none are configured", async () => {
    listedProviders = [];
    hasDecisionProviders = false;
    render(<TaskModels />);
    const links = await screen.findAllByRole("link", { name: "Add Provider" });
    expect(links).toHaveLength(2);
    links.forEach((link) =>
      expect(link).toHaveAttribute("href", "/admin/language-models")
    );
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  test("shows both selects in an error state when the listing fails", async () => {
    listingResponse = async () =>
      new Response(JSON.stringify({ detail: "Unavailable" }), { status: 503 });
    render(<TaskModels />);

    await waitFor(() =>
      expect(screen.getAllByRole("combobox")).toHaveLength(2)
    );
    screen
      .getAllByRole("combobox")
      .forEach((select) =>
        expect(select).toHaveAttribute("aria-invalid", "true")
      );
    expect(global.fetch).not.toHaveBeenCalledWith(
      "/api/admin/llm/default-chat-naming",
      expect.anything()
    );
  });

  test("shows the default row for both unset task models", async () => {
    await renderTaskModels();

    expect(await screen.findByText("Chat Naming Model")).toBeInTheDocument();
    expect(screen.getByText("Search Decision Model")).toBeInTheDocument();
    expect(taskSelector(0)).toHaveValue("Chat Default");
    expect(taskSelector(1)).toHaveValue("Chat Default");
    expect(screen.queryByText("(Optional)")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Reset" })
    ).not.toBeInTheDocument();
  });

  test("opts into a decision model and clears it without a chat fallback", async () => {
    const user = setupUser();
    render(<DecisionModelSetting />);
    const input = await screen.findByPlaceholderText("Not configured");
    expect(
      screen.queryByRole("button", { name: "Clear" })
    ).not.toBeInTheDocument();
    await user.click(input);
    await user.click(await screen.findByText("Decision Model A"));
    await waitFor(() =>
      expect(decisionModel).toEqual({ provider_id: 7, model_name: "decisions" })
    );
    expect(global.fetch).toHaveBeenCalledWith(
      SWR_KEYS.decisionModel,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ provider_id: 7, model_name: "decisions" }),
      })
    );
    await user.click(await screen.findByRole("button", { name: "Clear" }));
    await waitFor(() => expect(decisionModel).toBeNull());
    expect(await screen.findByPlaceholderText("Not configured")).toHaveValue(
      ""
    );
    expect(defaultChatNaming).toBeNull();
    expect(defaultSearchSelection).toBeNull();
  });

  test("does not offer hidden models", async () => {
    const user = setupUser();
    await renderTaskModels();

    await user.click(taskSelector(0));
    await user.type(
      screen.getByRole("textbox", { name: "Search" }),
      "GPT Legacy"
    );

    expect(
      screen.queryByRole("option", { name: /GPT Legacy/ })
    ).not.toBeInTheDocument();
  });

  test("keeps a hidden current model listed", async () => {
    defaultChatNaming = { provider_id: 7, model_name: "gpt-legacy" };
    await renderTaskModels();

    expect(await screen.findByDisplayValue("GPT Legacy")).toBeInTheDocument();
  });

  test("saves a chat naming model", async () => {
    const user = setupUser();
    await renderTaskModels();
    await screen.findByText("Chat Naming Model");

    await user.click(taskSelector(0));
    await user.type(
      screen.getByRole("textbox", { name: "Search" }),
      "GPT-6 Luna"
    );
    await user.click(screen.getByRole("option", { name: /GPT-6 Luna/ }));

    expect(await screen.findByDisplayValue("GPT-6 Luna")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/admin/llm/default-chat-naming",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider_id: 7, model_name: "gpt-6-luna" }),
      }
    );
    expect(toast.success).not.toHaveBeenCalled();
  });

  test("keeps the chat fallback after a failed save and re-enables the selector", async () => {
    mutationResponse = async () =>
      new Response(JSON.stringify({ detail: "Provider is unavailable" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    const user = setupUser();
    await renderTaskModels();
    await screen.findByText("Chat Naming Model");

    const selector = taskSelector(0);
    await user.click(selector);
    await user.type(
      screen.getByRole("textbox", { name: "Search" }),
      "GPT-6 Luna"
    );
    await user.click(screen.getByRole("option", { name: /GPT-6 Luna/ }));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Provider is unavailable");
    });
    expect(selector).toHaveValue("Chat Default");
    expect(selector).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: "Reset" })
    ).not.toBeInTheDocument();
  });

  test("picking Chat Default clears the chat naming model", async () => {
    defaultChatNaming = { provider_id: 7, model_name: "gpt-6-luna" };
    const user = setupUser();
    await renderTaskModels();
    const selector = await screen.findByDisplayValue("GPT-6 Luna");

    await user.click(selector);
    await user.click(screen.getByRole("option", { name: /Chat Default/ }));

    await waitFor(() => expect(selector).toHaveValue("Chat Default"));
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/admin/llm/default-chat-naming",
      { method: "DELETE" }
    );
  });

  test("saving a search model leaves the naming default unchanged", async () => {
    defaultChatNaming = { provider_id: 7, model_name: "gpt-6-luna" };
    const user = setupUser();
    await renderTaskModels();
    await screen.findByDisplayValue("GPT-6 Luna");
    const selector = taskSelector(1);
    await user.click(selector);
    await user.type(
      screen.getByRole("textbox", { name: "Search" }),
      "Search Mini"
    );
    await user.click(screen.getByRole("option", { name: /Search Mini/ }));

    expect(await screen.findByDisplayValue("Search Mini")).toBeInTheDocument();
    expect(screen.getByDisplayValue("GPT-6 Luna")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/admin/llm/default-search-selection",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider_id: 8, model_name: "search-mini" }),
      }
    );
    expect(toast.success).not.toHaveBeenCalled();
  });

  test("picking a decision model for search sets it and clears the search selection model", async () => {
    defaultSearchSelection = { provider_id: 8, model_name: "search-mini" };
    const user = setupUser();
    await renderTaskModels();
    await screen.findByDisplayValue("Search Mini");

    await user.click(taskSelector(1));
    await user.type(
      screen.getByRole("textbox", { name: "Search" }),
      "Decision Model A"
    );
    await user.click(screen.getByRole("option", { name: /Decision Model A/ }));

    await waitFor(() =>
      expect(decisionModel).toEqual({ provider_id: 7, model_name: "decisions" })
    );
    await waitFor(() => expect(defaultSearchSelection).toBeNull());
    expect(
      await screen.findByDisplayValue("Decision Model A")
    ).toBeInTheDocument();
  });

  test("picking a language model for search clears the decision model", async () => {
    decisionModel = { provider_id: 7, model_name: "decisions" };
    const user = setupUser();
    await renderTaskModels();
    await screen.findByDisplayValue("Decision Model A");

    await user.click(taskSelector(1));
    await user.type(
      screen.getByRole("textbox", { name: "Search" }),
      "Search Mini"
    );
    await user.click(screen.getByRole("option", { name: /Search Mini/ }));

    await waitFor(() =>
      expect(defaultSearchSelection).toEqual({
        provider_id: 8,
        model_name: "search-mini",
      })
    );
    await waitFor(() => expect(decisionModel).toBeNull());
  });

  test("shows the stored model when the second write of a search pick fails", async () => {
    defaultSearchSelection = { provider_id: 8, model_name: "search-mini" };
    searchMutationResponse = async () =>
      new Response(JSON.stringify({ detail: "Clear failed" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    const user = setupUser();
    await renderTaskModels();
    await screen.findByDisplayValue("Search Mini");

    await user.click(taskSelector(1));
    await user.type(
      screen.getByRole("textbox", { name: "Search" }),
      "Decision Model A"
    );
    await user.click(screen.getByRole("option", { name: /Decision Model A/ }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Clear failed")
    );
    // The decision model was stored before the failure, so it is shown.
    expect(
      await screen.findByDisplayValue("Decision Model A")
    ).toBeInTheDocument();
    expect(taskSelector(1)).toBeEnabled();
  });
});
