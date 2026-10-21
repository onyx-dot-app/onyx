import {
  act,
  deferred,
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { toast } from "@opal/layouts";
import { NextIntlClientProvider } from "next-intl";
import OpalStringsBridge from "@/i18n/OpalStringsBridge";
import frenchMessages from "@/i18n/messages/fr.json";
import ChatTaskModelSettings from "@/views/admin/ChatTaskModelSettings";
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

async function renderTaskModels(): Promise<void> {
  render(<ChatTaskModelSettings />);
  await screen.findByText("Chat naming model");
}

describe("ChatTaskModelSettings", () => {
  let defaultChatNaming: DefaultModel | null;
  let defaultSearchSelection: DefaultModel | null;
  let mutationResponse: () => Promise<Response>;
  let searchMutationResponse: () => Promise<Response>;
  let listedProviders: LLMProviderView[];
  let listingResponse: (() => Promise<Response>) | null;

  beforeEach(() => {
    defaultChatNaming = null;
    defaultSearchSelection = null;
    listedProviders = providers;
    listingResponse = null;
    mutationResponse = async () => new Response(null, { status: 204 });
    searchMutationResponse = async () => new Response(null, { status: 204 });
    jest.spyOn(toast, "success").mockReturnValue("success-toast");
    jest.spyOn(toast, "error").mockReturnValue("error-toast");
    jest.spyOn(global, "fetch").mockImplementation(async (input, init) => {
      if (input === "/api/admin/llm/default-chat-naming") {
        const response = await mutationResponse();
        if (response.ok) {
          defaultChatNaming =
            init?.method === "DELETE"
              ? null
              : { provider_id: 7, model_name: "gpt-4o-mini" };
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
            default_text: { provider_id: 7, model_name: "gpt-4o" },
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

  test("translates both optional suffixes through the Opal strings bridge", async () => {
    render(
      <NextIntlClientProvider locale="fr" messages={frenchMessages}>
        <OpalStringsBridge>
          <ChatTaskModelSettings />
        </OpalStringsBridge>
      </NextIntlClientProvider>
    );

    expect(await screen.findAllByText("(Facultatif)")).toHaveLength(2);
    expect(screen.queryByText("(Optional)")).not.toBeInTheDocument();
  });

  test("waits for provider data before rendering task controls", async () => {
    const pending = deferred<Response>();
    listingResponse = () => pending.promise;
    render(<ChatTaskModelSettings />);
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
    expect(await screen.findByText("Chat naming model")).toBeInTheDocument();
  });

  test("offers provider setup when none are configured", async () => {
    listedProviders = [];
    render(<ChatTaskModelSettings />);
    expect(
      await screen.findByText("Connect a language model provider")
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add Provider" })).toHaveAttribute(
      "href",
      "/admin/language-models"
    );
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  test("shows a provider-load failure and retries without changing defaults", async () => {
    listingResponse = async () =>
      new Response(JSON.stringify({ detail: "Unavailable" }), { status: 503 });
    const user = setupUser();
    render(<ChatTaskModelSettings />);
    expect(
      await screen.findByText("Could not load task models")
    ).toBeInTheDocument();
    listingResponse = null;
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Chat naming model")).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalledWith(
      "/api/admin/llm/default-chat-naming",
      expect.anything()
    );
  });

  test("shows the chat fallback only inside the empty naming selector", async () => {
    await renderTaskModels();

    expect(await screen.findByText("Chat naming model")).toBeInTheDocument();
    expect(screen.getByText("Search selection model")).toBeInTheDocument();
    expect(screen.getAllByPlaceholderText("Use Default model")).toHaveLength(2);
    expect(screen.queryByText("Session model")).not.toBeInTheDocument();
    expect(screen.getAllByDisplayValue("")).toHaveLength(2);
    expect(screen.queryByText("Chat Naming Model")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Reset" })
    ).not.toBeInTheDocument();
  });

  test("saves a hidden model without changing model visibility", async () => {
    const user = setupUser();
    await renderTaskModels();
    await screen.findByText("Chat naming model");

    await user.click(
      within(
        screen.getByRole("group", { name: "Chat naming model" })
      ).getByRole("combobox")
    );
    await user.type(
      screen.getByRole("textbox", { name: "Search" }),
      "GPT-4o Mini"
    );
    await user.click(screen.getByRole("option", { name: /GPT-4o Mini/ }));

    expect(await screen.findByDisplayValue("GPT-4o Mini")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/admin/llm/default-chat-naming",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider_id: 7, model_name: "gpt-4o-mini" }),
      }
    );
    expect(toast.success).toHaveBeenCalledWith("Chat naming model updated");
  });

  test("disables naming controls during reset and then returns to the chat fallback", async () => {
    defaultChatNaming = { provider_id: 7, model_name: "gpt-4o-mini" };
    const pending = deferred<Response>();
    mutationResponse = () => pending.promise;
    const user = setupUser();
    await renderTaskModels();
    const selector = await screen.findByDisplayValue("GPT-4o Mini");

    await user.click(screen.getByRole("button", { name: "Reset" }));

    expect(selector).toBeDisabled();
    expect(
      within(
        screen.getByRole("group", { name: "Search selection model" })
      ).getByRole("combobox")
    ).toBeEnabled();
    expect(screen.getByRole("button", { name: "Reset" })).toBeDisabled();
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/admin/llm/default-chat-naming",
      {
        method: "DELETE",
      }
    );

    await act(async () => pending.resolve(new Response(null, { status: 204 })));

    await waitFor(() => expect(selector).toHaveValue(""));
    expect(selector).toHaveAttribute("placeholder", "Use Default model");
    expect(selector).toHaveValue("");
    expect(selector).toBeEnabled();
    expect(toast.success).toHaveBeenCalledWith(
      "Chat naming model reset to the default model"
    );
  });

  test("keeps the chat naming model when its title is clicked", async () => {
    defaultChatNaming = { provider_id: 7, model_name: "gpt-4o-mini" };
    const user = setupUser();
    await renderTaskModels();
    await screen.findByDisplayValue("GPT-4o Mini");

    await user.click(screen.getByText("Chat naming model"));

    expect(screen.getByDisplayValue("GPT-4o Mini")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset" })).toBeEnabled();
    expect(global.fetch).not.toHaveBeenCalledWith(
      "/api/admin/llm/default-chat-naming",
      {
        method: "DELETE",
      }
    );
  });

  test("keeps the chat fallback after a failed save and re-enables the selector", async () => {
    mutationResponse = async () =>
      new Response(JSON.stringify({ detail: "Provider is unavailable" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    const user = setupUser();
    await renderTaskModels();
    await screen.findByText("Chat naming model");

    const selector = within(
      screen.getByRole("group", { name: "Chat naming model" })
    ).getByRole("combobox");
    await user.click(selector);
    await user.type(
      screen.getByRole("textbox", { name: "Search" }),
      "GPT-4o Mini"
    );
    await user.click(screen.getByRole("option", { name: /GPT-4o Mini/ }));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Provider is unavailable");
    });
    expect(selector).toHaveAttribute("placeholder", "Use Default model");
    expect(selector).toHaveValue("");
    expect(selector).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: "Reset" })
    ).not.toBeInTheDocument();
  });

  test("shows defaults from different providers and resets search independently", async () => {
    defaultChatNaming = { provider_id: 7, model_name: "gpt-4o-mini" };
    defaultSearchSelection = { provider_id: 8, model_name: "search-mini" };
    const pending = deferred<Response>();
    searchMutationResponse = () => pending.promise;
    const user = setupUser();
    await renderTaskModels();
    const searchSelector = await screen.findByDisplayValue("Search Mini");
    const namingSelector = screen.getByDisplayValue("GPT-4o Mini");

    await user.click(
      within(
        screen.getByRole("group", { name: "Search selection model" })
      ).getByRole("button", { name: "Reset" })
    );

    expect(searchSelector).toBeDisabled();
    expect(namingSelector).toBeEnabled();
    expect(screen.getAllByRole("button", { name: "Reset" })[0]).toBeEnabled();
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/admin/llm/default-search-selection",
      { method: "DELETE" }
    );
    await act(async () => pending.resolve(new Response(null, { status: 204 })));
    await waitFor(() => expect(searchSelector).toHaveValue(""));
    expect(namingSelector).toHaveValue("GPT-4o Mini");
    expect(toast.success).toHaveBeenCalledWith(
      "Search selection model reset to the default model"
    );
  });

  test("saving a hidden search model leaves naming and chat defaults unchanged", async () => {
    defaultChatNaming = { provider_id: 7, model_name: "gpt-4o-mini" };
    const user = setupUser();
    await renderTaskModels();
    await screen.findByDisplayValue("GPT-4o Mini");
    const selector = within(
      screen.getByRole("group", { name: "Search selection model" })
    ).getByRole("combobox");
    await user.click(selector);
    await user.type(
      screen.getByRole("textbox", { name: "Search" }),
      "Search Mini"
    );
    await user.click(screen.getByRole("option", { name: /Search Mini/ }));

    expect(await screen.findByDisplayValue("Search Mini")).toBeInTheDocument();
    expect(screen.getByDisplayValue("GPT-4o Mini")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/admin/llm/default-search-selection",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider_id: 8, model_name: "search-mini" }),
      }
    );
    expect(toast.success).toHaveBeenCalledWith(
      "Search selection model updated"
    );
    expect(providers[1]?.model_configurations[0]?.is_visible).toBe(false);

    expect(providers[0]?.model_configurations[1]?.is_visible).toBe(false);
  });

  test("search saves while a naming reset is pending without sharing its state", async () => {
    defaultChatNaming = { provider_id: 7, model_name: "gpt-4o-mini" };
    const pending = deferred<Response>();
    mutationResponse = () => pending.promise;
    const user = setupUser();
    await renderTaskModels();
    const namingSelector = await screen.findByDisplayValue("GPT-4o Mini");
    await user.click(screen.getByRole("button", { name: "Reset" }));
    expect(namingSelector).toBeDisabled();

    await user.click(
      within(
        screen.getByRole("group", { name: "Search selection model" })
      ).getByRole("combobox")
    );
    await user.type(
      screen.getByRole("textbox", { name: "Search" }),
      "Search Mini"
    );
    await user.click(screen.getByRole("option", { name: /Search Mini/ }));
    expect(await screen.findByDisplayValue("Search Mini")).toBeEnabled();
    expect(namingSelector).toBeDisabled();

    await act(async () => pending.resolve(new Response(null, { status: 204 })));
    await waitFor(() => expect(namingSelector).toHaveValue(""));
    expect(screen.getByDisplayValue("Search Mini")).toBeInTheDocument();
  });

  test("a failed search reset preserves both defaults and re-enables controls", async () => {
    defaultChatNaming = { provider_id: 7, model_name: "gpt-4o-mini" };
    defaultSearchSelection = { provider_id: 8, model_name: "search-mini" };
    searchMutationResponse = async () =>
      new Response(JSON.stringify({ detail: "Provider is unavailable" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    const user = setupUser();
    await renderTaskModels();
    const selector = await screen.findByDisplayValue("Search Mini");
    await user.click(
      within(
        screen.getByRole("group", { name: "Search selection model" })
      ).getByRole("button", { name: "Reset" })
    );
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Provider is unavailable");
    });
    expect(selector).toHaveValue("Search Mini");
    expect(selector).toBeEnabled();
    expect(screen.getByDisplayValue("GPT-4o Mini")).toBeInTheDocument();
  });
});
