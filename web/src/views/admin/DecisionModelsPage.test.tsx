import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import DecisionModelsPage from "@/views/admin/DecisionModelsPage";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { LLMProviderView } from "@/lib/languageModels/types";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ back: jest.fn() }),
  usePathname: () => "/admin/decision-models",
}));

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ hide_provider_grouping: false }),
}));

const typesafeModel = {
  name: "system-one",
  display_name: "System One",
  is_visible: false,
  max_input_tokens: null,
  supports_image_input: false,
  supports_reasoning: false,
  supports_chat: false,
  supports_decisions: true,
};
const savedTypeSafe: LLMProviderView = {
  id: 8,
  name: "TypeSafe connection",
  provider: "typesafe",
  api_key: null,
  api_base: null,
  api_version: null,
  deployment_name: null,
  custom_config: null,
  is_public: true,
  is_auto_mode: false,
  groups: [],
  personas: [],
  model_configurations: [
    { ...typesafeModel, effectiveDisplayName: "System One" },
  ],
};

afterEach(() => jest.restoreAllMocks());

function mockApi(hasTypeSafeConnection = false, selected = false) {
  return jest.spyOn(global, "fetch").mockImplementation(async (url) => {
    if (url === SWR_KEYS.decisionModel)
      return new Response(
        JSON.stringify({
          model: selected ? { provider_id: 8, model_name: "system-one" } : null,
          providers: hasTypeSafeConnection ? [savedTypeSafe] : [],
          supported_providers: ["typesafe", "openai", "openrouter"],
        })
      );
    if (url === SWR_KEYS.adminLlmProvidersPaged)
      return new Response(
        JSON.stringify({
          providers: hasTypeSafeConnection ? [savedTypeSafe] : [],
          default_text: null,
        })
      );
    if (url === SWR_KEYS.wellKnownLlmProvider("typesafe"))
      return new Response(
        JSON.stringify({
          name: "typesafe",
          known_models: [typesafeModel],
          recommended_default_model: null,
        })
      );
    if (url === SWR_KEYS.adminLlmProvider(8))
      return new Response(JSON.stringify(savedTypeSafe));
    if (String(url).startsWith(SWR_KEYS.adminLlmProviders))
      return new Response(JSON.stringify(savedTypeSafe));
    throw new Error(`Unexpected URL ${String(url)}`);
  });
}

it("shows the provider catalog without choosing a decision model", async () => {
  const fetchSpy = mockApi();
  render(<DecisionModelsPage />);
  expect(await screen.findByText("Decision Models")).toBeInTheDocument();
  expect(await screen.findByPlaceholderText("Not configured")).toHaveValue("");
  expect(screen.getAllByRole("button", { name: "Connect" })).toHaveLength(3);
  expect(
    screen.getByText("TypeSafe AI", { selector: "span" })
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Clear" })
  ).not.toBeInTheDocument();
  expect(fetchSpy.mock.calls.every(([, init]) => !init?.method)).toBe(true);
});

it("loads the complete saved provider before editing a decision connection", async () => {
  const fetchSpy = mockApi(true);
  const user = setupUser();
  render(<DecisionModelsPage />);
  await user.click(await screen.findByRole("button", { name: "Configure" }));
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  expect(fetchSpy).toHaveBeenCalledWith(SWR_KEYS.adminLlmProvider(8));
  expect(await screen.findByLabelText(/api key/i)).toBeInTheDocument();
});

it("removes a decision-only provider through the existing delete endpoint", async () => {
  const fetchSpy = mockApi(true);
  const user = setupUser();
  render(<DecisionModelsPage />);
  await user.click(await screen.findByRole("button", { name: "Delete" }));
  await user.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" })
  );
  await waitFor(() =>
    expect(fetchSpy).toHaveBeenCalledWith(`${SWR_KEYS.adminLlmProviders}/8`, {
      method: "DELETE",
    })
  );
});

it("requires clearing the selected decision model before removing its provider", async () => {
  const fetchSpy = mockApi(true, true);
  const user = setupUser();
  render(<DecisionModelsPage />);
  await user.click(await screen.findByRole("button", { name: "Delete" }));
  const dialog = screen.getByRole("dialog");
  expect(
    within(dialog).getByText(
      "Clear the selected decision model before removing this provider."
    )
  ).toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: "Delete" })).toBeDisabled();
  expect(
    fetchSpy.mock.calls.every(([, init]) => init?.method !== "DELETE")
  ).toBe(true);
});

it("refetches a cached provider list that another page made stale", async () => {
  mockApi();
  render(<DecisionModelsPage />, {
    swrConfig: {
      provider: () =>
        new Map([
          [
            SWR_KEYS.adminLlmProvidersPaged,
            { data: { providers: [savedTypeSafe], default_text: null } },
          ],
        ]),
    },
  });
  await waitFor(() =>
    expect(screen.getAllByRole("button", { name: "Connect" })).toHaveLength(3)
  );
  expect(
    screen.queryByRole("button", { name: "Configure" })
  ).not.toBeInTheDocument();
});
