import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { PointerEventsCheckLevel } from "@testing-library/user-event";
import OpenAIModal from "@/sections/modals/languageModels/OpenAIModal";
import type {
  LLMProviderView,
  WellKnownLLMProviderDescriptor,
} from "@/lib/languageModels/types";
import { SWR_KEYS } from "@/lib/swr-keys";

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
    <OpenAIModal
      modelScope="decision"
      existingLlmProvider={provider}
      shouldMarkAsDefault
      onSuccess={onSuccess}
    />
  );

  expect(await screen.findByText("OpenAI Decisions")).toBeInTheDocument();
  expect(screen.queryByText("Chat Model")).not.toBeInTheDocument();
  expect(screen.queryByText("Auto-update models")).not.toBeInTheDocument();
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
    ([url]) => url === SWR_KEYS.adminLlmProviders
  )?.[1];
  expect(JSON.parse(String(request?.body))).toMatchObject({
    id: 7,
    model_configuration_scope: "decision",
    is_auto_mode: false,
    model_configurations: [{ name: "gpt-6-luna", is_visible: false }],
  });
  expect(JSON.parse(String(request?.body)).model_configurations).toHaveLength(
    1
  );
  expect(fetchSpy).not.toHaveBeenCalledWith(
    "/api/admin/llm/default",
    expect.anything()
  );
  expect(fetchSpy).toHaveBeenCalledWith(
    "/api/admin/llm/test",
    expect.objectContaining({
      body: expect.stringContaining('"model_configuration_scope":"decision"'),
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
    <OpenAIModal
      modelScope="decision"
      existingLlmProvider={provider}
      onSuccess={onSuccess}
    />
  );
  await user.click(await screen.findByRole("button", { name: "Deselect All" }));
  await user.click(screen.getByRole("button", { name: "Update" }));
  await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
  const request = fetchSpy.mock.calls.find(
    ([url]) => url === SWR_KEYS.adminLlmProviders
  )?.[1];
  expect(JSON.parse(String(request?.body))).toMatchObject({
    model_configuration_scope: "decision",
    model_configurations: [],
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
    <OpenAIModal modelScope="decision" existingLlmProvider={existing} />
  );
  expect(screen.queryByText("OpenAI Decisions")).not.toBeInTheDocument();
  mockKnownProvider = {
    name: "openai",
    known_models: provider.model_configurations,
    recommended_default_model: null,
  };
  rendered.rerender(
    <OpenAIModal modelScope="decision" existingLlmProvider={existing} />
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
  render(<OpenAIModal modelScope="decision" existingLlmProvider={existing} />);
  expect(await screen.findByText("OpenAI Decisions")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Select All" })
  ).toBeInTheDocument();
});
