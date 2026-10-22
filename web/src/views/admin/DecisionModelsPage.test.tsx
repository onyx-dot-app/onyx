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
  selected = false,
  configuredProvider = savedZoom
) {
  return jest.spyOn(global, "fetch").mockImplementation(async (url) => {
    if (url === SWR_KEYS.decisionModel)
      return new Response(
        JSON.stringify({
          model: selected
            ? { provider_id: 8, model_name: "zoom-decisions" }
            : null,
          providers: hasZoomConnection ? [configuredProvider] : [],
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
          providers: hasZoomConnection ? [configuredProvider] : [],
          default_text: null,
        })
      );
    if (url === SWR_KEYS.voiceProviders)
      return new Response(
        JSON.stringify(
          hasScribeConnection
            ? [
                {
                  id: 4,
                  provider_type: "zoom",
                  name: "Company Scribe",
                  api_key: "masked-key",
                  api_secret: "masked-secret",
                  is_default_stt: true,
                  is_default_tts: false,
                  stt_model: "scribe-live",
                  tts_model: null,
                  default_voice: null,
                  custom_config: { language: "en-US" },
                  target_uri: null,
                },
              ]
            : []
        )
      );
    if (String(url).startsWith(SWR_KEYS.voiceProviders))
      return new Response(JSON.stringify({ success: true }));
    if (url === SWR_KEYS.wellKnownLlmProvider("zoom_ai"))
      return new Response(
        JSON.stringify({
          name: "zoom_ai",
          known_models: [zoomModel],
          recommended_default_model: null,
        })
      );
    if (url === SWR_KEYS.adminLlmProvider(8))
      return new Response(JSON.stringify(configuredProvider));
    if (String(url).startsWith(SWR_KEYS.adminLlmProviders))
      return new Response(JSON.stringify(configuredProvider));
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

it("reuses the saved Zoom credentials and preserves opt-in defaults", async () => {
  const fetchSpy = mockApi();
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(<DecisionModelsPage />);
  // Cards are labelled by their provider's name; unconnected Zoom reads "Zoom".
  const card = await screen.findByLabelText("Zoom");
  await user.click(within(card).getByRole("button", { name: "Connect" }));
  await user.click(await screen.findByRole("button", { name: "Update" }));
  await waitFor(() =>
    expect(fetchSpy).toHaveBeenCalledWith(
      SWR_KEYS.voiceProviders,
      expect.objectContaining({ method: "POST" })
    )
  );
  const request = fetchSpy.mock.calls.find(
    ([url, init]) => url === SWR_KEYS.voiceProviders && init?.method === "POST"
  )?.[1];
  expect(JSON.parse(String(request?.body))).toMatchObject({
    id: 4,
    provider_type: "zoom",
    validation_mode: "decision",
    activate_stt: false,
    activate_tts: false,
    api_key_changed: false,
    api_secret_changed: false,
  });
  expect(JSON.parse(String(request?.body))).not.toHaveProperty("api_key");
  expect(JSON.parse(String(request?.body))).not.toHaveProperty("api_secret");
  const testRequest = fetchSpy.mock.calls.find(
    ([url]) => url === `${SWR_KEYS.voiceProviders}/test`
  )?.[1];
  expect(JSON.parse(String(testRequest?.body))).toMatchObject({
    id: 4,
    validation_mode: "decision",
    use_stored_key: true,
    use_stored_secret: true,
  });
});

it("creates the shared Zoom connection directly from Decision Models", async () => {
  const fetchSpy = mockApi(false, false);
  const user = setupUser();
  render(<DecisionModelsPage />);
  // Cards are labelled by their provider's name; unconnected Zoom reads "Zoom".
  const card = await screen.findByLabelText("Zoom");
  await user.click(within(card).getByRole("button", { name: "Connect" }));
  await user.type(await screen.findByLabelText("API Key"), "new-zoom-key");
  await user.type(screen.getByLabelText("API Secret"), "new-zoom-secret");
  expect(
    within(screen.getByRole("dialog")).queryByRole("combobox")
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /^Connect$/ }));
  await waitFor(() =>
    expect(fetchSpy).toHaveBeenCalledWith(
      SWR_KEYS.voiceProviders,
      expect.objectContaining({ method: "POST" })
    )
  );
  const request = fetchSpy.mock.calls.find(
    ([url, init]) => url === SWR_KEYS.voiceProviders && init?.method === "POST"
  )?.[1];
  expect(JSON.parse(String(request?.body))).toMatchObject({
    provider_type: "zoom",
    api_key: "new-zoom-key",
    api_secret: "new-zoom-secret",
    validation_mode: "decision",
    activate_stt: false,
    activate_tts: false,
  });
  expect(fetchSpy.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(
    false
  );
});

it("loads the complete saved provider before editing a decision connection", async () => {
  const fetchSpy = mockApi(true);
  const user = setupUser();
  render(<DecisionModelsPage />);
  await user.click(
    await screen.findByRole("button", {
      name: "Edit Zoom decisions connection",
    })
  );
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  expect(fetchSpy).toHaveBeenCalledWith(SWR_KEYS.adminLlmProvider(8));
  expect(
    await screen.findByRole("button", { name: "Update" })
  ).toBeInTheDocument();
});

it("rotates the shared Zoom key without resending the stored secret", async () => {
  const fetchSpy = mockApi(true);
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(<DecisionModelsPage />);
  await user.click(
    await screen.findByRole("button", {
      name: "Edit Zoom decisions connection",
    })
  );
  const key = await screen.findByLabelText("API Key");
  await user.clear(key);
  await user.type(key, "rotated-zoom-key");
  await user.click(screen.getByRole("button", { name: "Update" }));
  await waitFor(() =>
    expect(fetchSpy).toHaveBeenCalledWith(
      SWR_KEYS.voiceProviders,
      expect.objectContaining({ method: "POST" })
    )
  );
  const request = fetchSpy.mock.calls.find(
    ([url, init]) => url === SWR_KEYS.voiceProviders && init?.method === "POST"
  )?.[1];
  const body = JSON.parse(String(request?.body));
  expect(body).toMatchObject({
    id: 4,
    api_key: "rotated-zoom-key",
    api_key_changed: true,
    api_secret_changed: false,
    activate_stt: false,
    activate_tts: false,
  });
  expect(body).not.toHaveProperty("api_secret");
});

it("removes only the Zoom decision provider and keeps Scribe", async () => {
  const fetchSpy = mockApi(true);
  const user = setupUser();
  render(<DecisionModelsPage />);
  await user.click(
    await screen.findByRole("button", {
      name: "Delete Zoom decisions connection",
    })
  );
  await user.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" })
  );
  await waitFor(() =>
    expect(fetchSpy).toHaveBeenCalledWith(
      `${SWR_KEYS.adminLlmProviders}/8`,
      expect.objectContaining({ method: "DELETE" })
    )
  );
  expect(
    fetchSpy.mock.calls.some(
      ([url, init]) =>
        String(url).startsWith(String(SWR_KEYS.voiceProviders)) &&
        init?.method === "DELETE"
    )
  ).toBe(false);
});

it("requires clearing the selected decision model before removing its provider", async () => {
  const fetchSpy = mockApi(true, true, true);
  const user = setupUser();
  render(<DecisionModelsPage />);
  await user.click(
    await screen.findByRole("button", {
      name: "Delete Zoom decisions connection",
    })
  );
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
            { data: { providers: [savedZoom], default_text: null } },
          ],
        ]),
    },
  });
  await waitFor(() =>
    expect(screen.getAllByRole("button", { name: "Connect" })).toHaveLength(5)
  );
  expect(
    screen.queryByRole("button", { name: /^Edit / })
  ).not.toBeInTheDocument();
});
