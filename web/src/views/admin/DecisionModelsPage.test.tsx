import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import DecisionModelsPage from "@/views/admin/DecisionModelsPage";
import { PointerEventsCheckLevel } from "@testing-library/user-event";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { LLMProviderView } from "@/lib/languageModels/types";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ back: jest.fn() }),
  usePathname: () => "/admin/decision-models",
}));

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ hide_provider_grouping: false }),
}));

const zoomModel = {
  name: "zoom-decisions",
  display_name: "Zoom Decisions",
  is_visible: false,
  max_input_tokens: null,
  supports_image_input: false,
  supports_reasoning: false,
  supports_chat: false,
  supports_decisions: true,
};
const savedZoom: LLMProviderView = {
  id: 8,
  name: "Zoom decisions connection",
  provider: "zoom_ai",
  zoom_voice_provider_id: 4,
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
    { ...zoomModel, effectiveDisplayName: "Zoom Decisions" },
  ],
};

afterEach(() => jest.restoreAllMocks());

function mockApi(
  hasZoomConnection = false,
  hasScribeConnection = true,
  selected = false
) {
  return jest.spyOn(global, "fetch").mockImplementation(async (url) => {
    if (url === SWR_KEYS.decisionModel)
      return new Response(
        JSON.stringify({
          model: selected
            ? { provider_id: 8, model_name: "zoom-decisions" }
            : null,
          providers: hasZoomConnection ? [savedZoom] : [],
          supported_providers: [
            "typesafe",
            "openai",
            "openrouter",
            "vercel_ai_gateway",
            "zoom_ai",
          ],
        })
      );
    if (url === SWR_KEYS.adminLlmProvidersPaged)
      return new Response(
        JSON.stringify({
          providers: hasZoomConnection ? [savedZoom] : [],
          default_text: null,
        })
      );
    if (url === SWR_KEYS.voiceProviders)
      return new Response(
        JSON.stringify(
          hasScribeConnection
            ? [{ id: 4, provider_type: "zoom", name: "Company Scribe" }]
            : []
        )
      );
    if (url === SWR_KEYS.wellKnownLlmProvider("zoom_ai"))
      return new Response(
        JSON.stringify({
          name: "zoom_ai",
          known_models: [zoomModel],
          recommended_default_model: null,
        })
      );
    if (url === SWR_KEYS.adminLlmProvider(8))
      return new Response(JSON.stringify(savedZoom));
    if (String(url).startsWith(SWR_KEYS.adminLlmProviders))
      return new Response(JSON.stringify(savedZoom));
    throw new Error(`Unexpected URL ${String(url)}`);
  });
}

it("shows the provider catalog without choosing a decision model", async () => {
  const fetchSpy = mockApi();
  render(<DecisionModelsPage />);
  expect(await screen.findByText("Decision Models")).toBeInTheDocument();
  expect(await screen.findByPlaceholderText("Not configured")).toHaveValue("");
  expect(screen.getAllByRole("button", { name: "Connect" })).toHaveLength(5);
  expect(
    screen.getByText("TypeSafe AI", { selector: "span" })
  ).toBeInTheDocument();
  expect(screen.getByText("Vercel AI Gateway")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Clear" })
  ).not.toBeInTheDocument();
  expect(fetchSpy.mock.calls.every(([, init]) => !init?.method)).toBe(true);
});

it("connects Zoom through an existing Scribe record without copying credentials", async () => {
  const fetchSpy = mockApi();
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(<DecisionModelsPage />);
  const card = await screen.findByTestId("decision-provider-zoom_ai-new");
  await user.click(within(card).getByRole("button", { name: "Connect" }));
  await user.click(
    await screen.findByRole("combobox", {
      name: "Select a Zoom Scribe connection",
    })
  );
  await user.click(
    await screen.findByRole("option", { name: "Company Scribe" })
  );
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(fetchSpy).toHaveBeenCalledWith(
      `${SWR_KEYS.adminLlmProviders}?is_creation=true`,
      expect.objectContaining({ method: "PUT" })
    )
  );
  const request = fetchSpy.mock.calls.find(
    ([, init]) => init?.method === "PUT"
  )?.[1];
  expect(JSON.parse(String(request?.body))).toMatchObject({
    provider: "zoom_ai",
    zoom_voice_provider_id: 4,
    model_configuration_scope: "decision",
    model_configurations: [{ name: "zoom-decisions", is_visible: false }],
  });
  expect(JSON.parse(String(request?.body))).not.toHaveProperty("api_key");
  expect(JSON.parse(String(request?.body))).not.toHaveProperty("api_secret");
});

it("links to Voice setup when no saved Zoom Scribe connection exists", async () => {
  mockApi(false, false);
  const user = setupUser();
  render(<DecisionModelsPage />);
  const card = await screen.findByTestId("decision-provider-zoom_ai-new");
  await user.click(within(card).getByRole("button", { name: "Connect" }));
  expect(
    await screen.findByRole("link", { name: "Set up Voice" })
  ).toHaveAttribute("href", "/admin/voice");
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  expect(screen.queryByLabelText(/API key/i)).not.toBeInTheDocument();
});

it("loads the complete saved provider before editing a decision connection", async () => {
  const fetchSpy = mockApi(true);
  const user = setupUser();
  render(<DecisionModelsPage />);
  await user.click(await screen.findByRole("button", { name: "Configure" }));
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  expect(fetchSpy).toHaveBeenCalledWith(SWR_KEYS.adminLlmProvider(8));
  expect(
    await screen.findByRole("combobox", {
      name: "Select a Zoom Scribe connection",
    })
  ).toHaveValue("Company Scribe");
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
  const fetchSpy = mockApi(true, true, true);
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
