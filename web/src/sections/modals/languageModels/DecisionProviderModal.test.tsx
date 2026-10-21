import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { PointerEventsCheckLevel } from "@testing-library/user-event";
import DecisionProviderModal from "@/sections/modals/languageModels/DecisionProviderModal";
import type {
  LLMProviderView,
  WellKnownLLMProviderDescriptor,
} from "@/lib/languageModels/types";

let mockKnownProvider: WellKnownLLMProviderDescriptor | undefined;

jest.mock("@/lib/languageModels/hooks", () => ({
  useWellKnownLLMProvider: () => ({ wellKnownLLMProvider: mockKnownProvider }),
  useAdminLanguageModels: () => ({
    defaultText: { provider_id: 7, model_name: "chat-model" },
  }),
}));

const provider: LLMProviderView = {
  id: 7,
  name: "Saved OpenAI",
  provider: "openai",
  api_key: "********",
  api_base: null,
  api_version: null,
  custom_config: null,
  deployment_name: null,
  is_public: true,
  is_auto_mode: true,
  groups: [],
  personas: [],
  model_configurations: [
    {
      name: "chat-model",
      display_name: "Chat Model",
      effectiveDisplayName: "Chat Model",
      is_visible: true,
      max_input_tokens: null,
      supports_chat: true,
      supports_decisions: false,
      supports_image_input: false,
      supports_reasoning: false,
    },
    {
      name: "gpt-6-luna",
      display_name: "OpenAI Decisions",
      effectiveDisplayName: "OpenAI Decisions",
      is_visible: false,
      max_input_tokens: null,
      supports_chat: true,
      supports_decisions: true,
      supports_image_input: false,
      supports_reasoning: false,
    },
  ],
};

beforeEach(() => {
  mockKnownProvider = undefined;
});
afterEach(() => jest.restoreAllMocks());

it("edits only decision models and never assigns a chat default", async () => {
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(new Response(JSON.stringify(provider)));
  const onSuccess = jest.fn();
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <DecisionProviderModal
      providerName="openai"
      existingLlmProvider={provider}
      onSuccess={onSuccess}
    />
  );

  expect(await screen.findByText("OpenAI Decisions")).toBeInTheDocument();
  expect(screen.queryByText("Chat Model")).not.toBeInTheDocument();
  expect(screen.queryByText("Auto-update models")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Rename" })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Model Settings" })
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("link", {
      name: "Manage chat settings in Language Models",
    })
  ).toHaveAttribute("href", "/admin/language-models");
  await user.clear(screen.getByLabelText(/display name/i));
  await user.type(
    screen.getByLabelText(/display name/i),
    "Decision connection"
  );
  await user.clear(screen.getByLabelText(/API key/i));
  await user.type(screen.getByLabelText(/API key/i), "rotated-key");
  await user.click(screen.getByRole("button", { name: "Update" }));
  await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));

  const request = fetchSpy.mock.calls.find(
    ([url]) => url === "/api/admin/llm/decision-provider"
  )?.[1];
  expect(JSON.parse(String(request?.body))).toMatchObject({
    id: 7,
    selected_model_names: ["gpt-6-luna"],
  });
  expect(JSON.parse(String(request?.body))).not.toHaveProperty(
    "model_configurations"
  );
  expect(JSON.parse(String(request?.body))).not.toHaveProperty("is_auto_mode");
  expect(fetchSpy).not.toHaveBeenCalledWith(
    "/api/admin/llm/default",
    expect.anything()
  );
  expect(fetchSpy).toHaveBeenCalledWith(
    "/api/admin/llm/decision-provider/test",
    expect.objectContaining({
      body: expect.stringContaining('"model":"gpt-6-luna"'),
    })
  );
  expect(provider.model_configurations[0]?.is_visible).toBe(true);
});

it("can remove every decision model without submitting shared chat models", async () => {
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(new Response(JSON.stringify(provider)));
  const onSuccess = jest.fn();
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <DecisionProviderModal
      providerName="openai"
      existingLlmProvider={provider}
      onSuccess={onSuccess}
    />
  );
  await user.click(await screen.findByRole("button", { name: "Deselect All" }));
  await user.click(screen.getByRole("button", { name: "Update" }));
  await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
  const request = fetchSpy.mock.calls.find(
    ([url]) => url === "/api/admin/llm/decision-provider"
  )?.[1];
  expect(JSON.parse(String(request?.body))).toMatchObject({
    selected_model_names: [],
  });
});

it("adds decision options when the catalog loads after a saved chat connection", async () => {
  const existing = {
    ...provider,
    model_configurations: provider.model_configurations.map((model) => ({
      ...model,
      supports_decisions: false,
    })),
  };
  const rendered = render(
    <DecisionProviderModal
      providerName="openai"
      existingLlmProvider={existing}
    />
  );
  expect(screen.queryByText("OpenAI Decisions")).not.toBeInTheDocument();
  mockKnownProvider = {
    name: "openai",
    known_models: provider.model_configurations,
    recommended_default_model: null,
  };
  rendered.rerender(
    <DecisionProviderModal
      providerName="openai"
      existingLlmProvider={existing}
    />
  );
  expect(await screen.findByText("OpenAI Decisions")).toBeInTheDocument();
  expect(screen.queryByText("Chat Model")).not.toBeInTheDocument();
});

it("offers an unselected decision option when a shared model only has chat enabled", async () => {
  const existing = {
    ...provider,
    model_configurations: provider.model_configurations.map((model) => ({
      ...model,
      supports_decisions: false,
    })),
  };
  mockKnownProvider = {
    name: "openai",
    known_models: provider.model_configurations,
    recommended_default_model: null,
  };
  render(
    <DecisionProviderModal
      providerName="openai"
      existingLlmProvider={existing}
    />
  );
  expect(await screen.findByText("OpenAI Decisions")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Select All" })
  ).toBeInTheDocument();
});

it.each([true, false])(
  "keeps newly discovered decision models unselected on existing connections (cached: %s)",
  async (cached) => {
    const existing = {
      ...provider,
      model_configurations: provider.model_configurations.filter(
        (model) => !model.supports_decisions
      ),
    };
    const catalog = {
      name: "openai",
      known_models: provider.model_configurations.map((model) => ({
        ...model,
        is_visible: true,
      })),
      recommended_default_model: null,
    };
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(JSON.stringify(existing)));
    const user = setupUser({
      pointerEventsCheck: PointerEventsCheckLevel.Never,
    });
    mockKnownProvider = cached ? catalog : undefined;
    const rendered = render(
      <DecisionProviderModal
        providerName="openai"
        existingLlmProvider={existing}
      />
    );
    if (!cached) {
      expect(screen.queryByText("OpenAI Decisions")).not.toBeInTheDocument();
      mockKnownProvider = catalog;
      rendered.rerender(
        <DecisionProviderModal
          providerName="openai"
          existingLlmProvider={existing}
        />
      );
    }
    expect(await screen.findByText("OpenAI Decisions")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Select All" })
    ).toBeInTheDocument();
    await user.clear(screen.getByLabelText(/display name/i));
    await user.type(
      screen.getByLabelText(/display name/i),
      "Saved decision connection"
    );
    await user.click(screen.getByRole("button", { name: "Update" }));
    await waitFor(() =>
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/admin/llm/decision-provider",
        expect.objectContaining({ method: "PUT" })
      )
    );
    const request = fetchSpy.mock.calls.find(
      ([url]) => url === "/api/admin/llm/decision-provider"
    )?.[1];
    expect(JSON.parse(String(request?.body)).selected_model_names).toEqual([]);
  }
);

it("stops saving when changed decision credentials fail validation", async () => {
  const fetchSpy = jest.spyOn(global, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ detail: "Invalid decision credentials" }), {
      status: 400,
    })
  );
  const onSuccess = jest.fn();
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <DecisionProviderModal
      providerName="openai"
      existingLlmProvider={provider}
      onSuccess={onSuccess}
    />
  );
  await user.clear(screen.getByLabelText(/API key/i));
  await user.type(screen.getByLabelText(/API key/i), "bad-key");
  await user.click(screen.getByRole("button", { name: "Update" }));
  await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
  expect(fetchSpy).toHaveBeenCalledWith(
    "/api/admin/llm/decision-provider/test",
    expect.anything()
  );
  expect(onSuccess).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Update" })).toBeInTheDocument();
});

it("keeps catalog discoveries unselected and preserves saved selections on refresh", async () => {
  const saved = {
    ...provider,
    provider: "openrouter",
    api_base: "https://openrouter.ai/api/v1",
  };
  const fetchSpy = jest.spyOn(global, "fetch").mockImplementation(
    async (url) =>
      new Response(
        JSON.stringify(
          String(url).endsWith("available-models")
            ? [
                {
                  name: "new-decision",
                  display_name: "New Decision",
                  supports_decisions: true,
                  supports_chat: false,
                },
              ]
            : saved
        )
      )
  );
  const onSuccess = jest.fn();
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <DecisionProviderModal
      providerName="openrouter"
      existingLlmProvider={saved}
      onSuccess={onSuccess}
    />
  );
  await user.click(screen.getByRole("button", { name: "Refresh models" }));
  expect(
    await screen.findByRole("checkbox", { name: "New Decision" })
  ).not.toBeChecked();
  expect(
    screen.getByRole("checkbox", { name: "OpenAI Decisions" })
  ).toBeChecked();
  await user.clear(screen.getByLabelText(/display name/i));
  await user.type(
    screen.getByLabelText(/display name/i),
    "Refreshed connection"
  );
  await user.click(screen.getByRole("button", { name: "Update" }));
  await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
  const request = fetchSpy.mock.calls.find(
    ([url]) => url === "/api/admin/llm/decision-provider"
  )?.[1];
  expect(JSON.parse(String(request?.body)).selected_model_names).toEqual([
    "gpt-6-luna",
  ]);
});
